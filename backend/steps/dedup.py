"""Merge duplicate records by key columns.

params:
  keys: list[str]                 # rows equal on these are duplicates
  merge: "first" | "last" | "mean"  # how to merge numeric conflicts
  on_conflict: "keep_all" | "error" # abort when non-key values disagree
  merge_columns: list[str]        # columns eligible for mean merging;
                                  # default = numeric columns only;
                                  # other columns keep the first value

Each merged output row keeps the identity of the first member and its
lineage lists every source row absorbed into it, so a surviving result
always tells which original records it came from.
"""

import math

from .numbers import parse_number


def _as_number(value):
    number = parse_number(value)
    if number is not None and math.isfinite(number):
        return number
    return None


def _equal(a, b):
    na, nb = _as_number(a), _as_number(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a).strip() == str(b).strip()


def apply(rows, params):
    keys = params["keys"]
    merge = params.get("merge", "mean")
    on_conflict = params.get("on_conflict", "keep_all")
    merge_columns = params.get("merge_columns")

    groups = {}
    order = []
    for row in rows:
        key = tuple(str(row.get(k, "")).strip() for k in keys)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    value_columns = [c for c in sorted({c for row in rows for c in row
                                       if not c.startswith("_")})
                     if c not in keys]
    if merge_columns is None:
        merge_columns = [c for c in value_columns
                         if any(_as_number(r.get(c)) is not None for r in rows)]
    merge_columns = set(merge_columns)

    out = []
    lineage = {}
    conflicts = []
    merged_groups = 0
    removed_rows = 0
    affected_rows = []

    for key in order:
        members = groups[key]
        if len(members) == 1:
            row = dict(members[0])
            out.append(row)
            lineage[row["_id"]] = [members[0]["_id"]]
            continue

        merged_groups += 1
        removed_rows += len(members) - 1
        representative = dict(members[0])

        for col in value_columns:
            values = [m.get(col) for m in members]
            distinct = []
            for value in values:
                if not any(_equal(value, d) for d in distinct):
                    distinct.append(value)
            if len(distinct) <= 1:
                representative[col] = values[0]
                continue

            conflicts.append({
                "column": col,
                "keys": dict(zip(keys, key)),
                "values": values,
            })
            if col not in merge_columns:
                representative[col] = values[0]
            elif merge == "first":
                representative[col] = values[0]
            elif merge == "last":
                representative[col] = values[-1]
            elif merge == "mean":
                nums = [_as_number(v) for v in values]
                if all(n is not None for n in nums):
                    representative[col] = round(sum(nums) / len(nums), 6)
                else:
                    raise ValueError(
                        f"conflicting non-numeric values in '{col}' for "
                        f"{dict(zip(keys, key))}: {values} (cannot average)"
                    )
            else:
                raise ValueError(f"unknown merge strategy: {merge}")

        if conflicts and on_conflict == "error":
            latest = conflicts[-1]
            raise ValueError(
                f"duplicate records disagree on '{latest['column']}' for "
                f"{latest['keys']}: {latest['values']}"
            )

        out.append(representative)
        lineage[representative["_id"]] = [m["_id"] for m in members]
        affected_rows.append({
            "row_id": representative["_id"],
            "source_row_ids": [m["_id"] for m in members],
            "keys": dict(zip(keys, key)),
            "conflict_columns": sorted({c["column"] for c in conflicts
                                        if all(c["keys"].get(k) == v
                                               for k, v in zip(keys, key))}),
        })

    stats = {
        "keys": keys,
        "merge": merge,
        "duplicate_groups": merged_groups,
        "rows_removed": removed_rows,
        "conflicts": conflicts,
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
