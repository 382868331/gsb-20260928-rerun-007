"""Numeric validity gate with per-source anomaly policies.

params:
  columns: list[str]   # columns that must hold finite numbers
  source_column: str|None
                       # column naming the data source (lab, instrument...)
  rules: list[dict]    # one rule per (kind, source):
                       # {kind: missing|invalid|nonfinite,
                       #  source: str (omit/"*" = any source),
                       #  action: flag|drop|replace,
                       #  value: explicit replacement for replace}
  strict: bool         # default true: any anomaly without a matching rule
                       # aborts the run (nothing is published)

Actions:
* ``flag``    -- keep the row and the ORIGINAL cell value, mark the cell
                 in ``_anomalies`` so later numeric steps skip it and the
                 UI shows "pending review"; the value is never zero.
* ``drop``    -- exclude the row; its id and raw value stay in stats and
                 lineage so the exclusion can be traced back.
* ``replace`` -- use the explicit ``value`` from the rule (must itself be
                 finite for invalid/nonfinite anomalies).
"""
from . import values


def _flag(row, column, kind, raw, stage="validate"):
    new_row = dict(row)
    marked = dict(row.get(values.ANOMALIES_KEY) or {})
    marked[column] = {"kind": kind, "raw": raw, "stage": stage}
    new_row[values.ANOMALIES_KEY] = marked
    return new_row


def apply(rows, params):
    columns = params.get("columns")
    if not columns:
        raise ValueError("validate_numbers needs non-empty 'columns'")
    source_column = params.get("source_column")
    rules = params.get("rules") or []
    strict = params.get("strict", True)
    for rule in rules:
        values.validate_rule(rule)

    counts = {kind: 0 for kind in values.ANOMALY_KINDS}
    by_source = {}
    flagged = dropped = replaced = 0
    unresolved = []
    affected_rows = []
    out = []
    lineage = {}

    for row in rows:
        new_row = dict(row)
        row_alive = True
        source = row.get(source_column) if source_column else None
        source_key = "" if source is None else str(source).strip()
        for column in columns:
            raw = row.get(column)
            existing = (row.get(values.ANOMALIES_KEY) or {}).get(column)
            if existing:
                # already pending review: count once, do not recompute
                kind = existing.get("kind", values.KIND_INVALID)
                counts[kind] = counts.get(kind, 0) + 1
                by_source.setdefault(source_key, {}).setdefault(kind, 0)
                by_source[source_key][kind] += 1
                continue
            kind, number, raw_value = values.classify(raw)
            if kind == values.KIND_FINITE:
                continue
            counts[kind] += 1
            by_source.setdefault(source_key, {}).setdefault(kind, 0)
            by_source[source_key][kind] += 1
            policy = values.resolve_policy(kind, source_key, rules)
            detail = {
                "row_id": row["_id"], "column": column, "kind": kind,
                "before": raw_value,
            }
            if source_column:
                detail["source"] = source
            if policy is None:
                if strict:
                    unresolved.append(detail)
                continue
            action = policy["action"]
            detail["action"] = action
            if action == "drop":
                affected_rows.append(dict(detail, after=None))
                row_alive = False
                dropped += 1
                break
            if action == "replace":
                replacement = values.validate_rule(policy)
                new_row[column] = replacement
                replaced += 1
                affected_rows.append(dict(detail, after=replacement))
            else:  # flag
                new_row = _flag(new_row, column, kind, raw_value)
                flagged += 1
                affected_rows.append(dict(detail, after=raw_value, pending=True))
        if row_alive:
            out.append(new_row)
            lineage[new_row["_id"]] = [row["_id"]]

    if unresolved:
        details = "; ".join(
            f"{item['row_id']} {item['column']}={item['before']!r}"
            f"({values.describe_kind(item['kind'])})"
            for item in unresolved[:10]
        )
        more = "" if len(unresolved) <= 10 else f" ... (+{len(unresolved) - 10} more)"
        raise ValueError(
            f"{len(unresolved)} cell(s) have no anomaly policy: {details}{more}"
        )

    stats = {
        "columns": list(columns),
        "missing_cells": counts[values.KIND_MISSING],
        "invalid_text_cells": counts[values.KIND_INVALID],
        "nonfinite_cells": counts[values.KIND_NONFINITE],
        "rows_flagged": flagged,
        "rows_dropped": dropped,
        "rows_replaced": replaced,
        "by_source": by_source,
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
