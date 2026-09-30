"""Unit normalisation for a measurement column.

params:
  column: str            # value column, e.g. "temperature"
  unit_column: str|None  # column carrying the per-row source unit
  source_column: str|None# optional column naming the data source; used to
                         # pick per-source anomaly rules
  rules: {unit: factor | {"factor": f, "offset": b}}
  canonical_unit: str    # target unit label, e.g. "C"
  anomaly_rules: list    # optional per-source handling for values that are
                         # missing / illegal text / outside finite range,
                         # both before and after conversion:
                         # {kind, source?, action: flag|drop|replace, value?}

Validity is checked twice: the raw value must parse to a finite float and
the converted result must remain finite (a huge value times a factor can
overflow).  Unhandled anomalies abort the whole run with a message that
names the row id and the original value, so bad data is never silently
turned into zero or carried into the result as infinity.
"""
from . import values


def _factor_offset(rules, canonical_unit):
    factors = {}
    for unit, rule in (rules or {}).items():
        if isinstance(rule, dict):
            factors[str(unit).strip()] = (
                float(rule.get("factor", 1.0)), float(rule.get("offset", 0.0)))
        else:
            factors[str(unit).strip()] = (float(rule), 0.0)
    factors.setdefault(canonical_unit, (1.0, 0.0))
    return factors


def _already_flagged(row, column):
    marked = row.get(values.ANOMALIES_KEY) or {}
    return column in (marked or {})


def apply(rows, params):
    column = params["column"]
    unit_column = params.get("unit_column")
    source_column = params.get("source_column")
    rules = params.get("rules") or {}
    canonical_unit = params["canonical_unit"]
    anomaly_rules = params.get("anomaly_rules") or []
    for rule in anomaly_rules:
        values.validate_rule(rule)

    factors = _factor_offset(rules, canonical_unit)

    converted = 0
    unknown_units = {}
    unresolved = []
    dropped = 0
    flagged = 0
    replaced = 0
    counters = {kind: 0 for kind in values.ANOMALY_KINDS}
    affected_rows = []
    out = []
    lineage = {}

    for row in rows:
        raw_original = row.get(column)
        unit = canonical_unit
        if unit_column:
            raw_unit = row.get(unit_column)
            unit = str(raw_unit).strip() if raw_unit is not None else canonical_unit
        factor_offset = factors.get(unit)
        if factor_offset is None:
            unknown_units[unit] = unknown_units.get(unit, 0) + 1
            continue

        # A previous step already parked this cell as "pending review";
        # keep the original text untouched and skip arithmetic on it.
        if _already_flagged(row, column):
            new_row = dict(row)
            if unit_column:
                new_row[unit_column] = canonical_unit
            out.append(new_row)
            lineage[new_row["_id"]] = [row["_id"]]
            flagged += 1
            continue

        kind, number, raw = values.classify(raw_original)
        factor, offset_value = factor_offset
        new_row = dict(row)

        if kind != values.KIND_FINITE:
            counters[kind] += 1
            source = row.get(source_column) if source_column else None
            policy = values.resolve_policy(
                kind, "" if source is None else str(source).strip(),
                anomaly_rules)
            detail = {
                "row_id": row["_id"], "column": column, "kind": kind,
                "before": raw, "unit": unit,
            }
            if source_column:
                detail["source"] = source
            if policy is None and kind == values.KIND_MISSING:
                # No explicit policy for missing cells: leave the raw
                # value in place for a later missing-values step; the
                # unit label is still normalised below.
                out_row = new_row
                if unit_column:
                    out_row[unit_column] = canonical_unit
                out.append(out_row)
                lineage[out_row["_id"]] = [row["_id"]]
                continue
            if policy is None:
                unresolved.append(detail)
                continue
            action = policy["action"]
            detail["action"] = action
            if action == "drop":
                dropped += 1
                affected_rows.append(dict(detail, after=None))
                continue
            if action == "replace":
                replacement = values.validate_rule(policy)
                # replacement is finite for invalid/nonfinite; missing may
                # be any explicit value and is left for a later step
                if kind == values.KIND_MISSING and not isinstance(
                        replacement, float):
                    new_row[column] = replacement
                    out_row = new_row
                    if unit_column:
                        out_row[unit_column] = canonical_unit
                    out.append(out_row)
                    lineage[out_row["_id"]] = [row["_id"]]
                    replaced += 1
                    affected_rows.append(dict(detail, after=replacement))
                    continue
                number = replacement
                converted_value = values.finite_result(
                    number * factor + offset_value)
                if converted_value is None:
                    unresolved.append(dict(detail, kind=values.KIND_NONFINITE,
                                           note="replacement overflows"))
                    continue
                new_row[column] = round(converted_value, 6)
                replaced += 1
                affected_rows.append(dict(detail, after=new_row[column]))
            else:  # flag: keep the raw value, mark pending review
                flagged += 1
                marked = dict(row.get(values.ANOMALIES_KEY) or {})
                marked[column] = {
                    "kind": kind, "raw": raw, "stage": "unit_convert",
                    "unit": unit,
                }
                new_row[values.ANOMALIES_KEY] = marked
                affected_rows.append(dict(detail, after=raw, pending=True))
            if unit_column:
                new_row[unit_column] = canonical_unit
            out.append(new_row)
            lineage[new_row["_id"]] = [row["_id"]]
            continue

        converted_value = values.finite_result(number * factor + offset_value)
        if converted_value is None:
            # finite raw value, but conversion escapes the finite range
            counters[values.KIND_NONFINITE] += 1
            source = row.get(source_column) if source_column else None
            policy = values.resolve_policy(
                values.KIND_NONFINITE,
                "" if source is None else str(source).strip(),
                anomaly_rules)
            detail = {
                "row_id": row["_id"], "column": column,
                "kind": values.KIND_NONFINITE, "before": raw, "unit": unit,
                "stage": "after_conversion",
            }
            if policy is None:
                unresolved.append(detail)
                continue
            action = policy["action"]
            detail["action"] = action
            if action == "drop":
                dropped += 1
                affected_rows.append(dict(detail, after=None))
                continue
            if action == "replace":
                replacement = values.validate_rule(policy)
                if not isinstance(replacement, float):
                    unresolved.append(detail)
                    continue
                replaced_value = values.finite_result(
                    replacement * factor + offset_value)
                if replaced_value is None:
                    unresolved.append(dict(detail, note="replacement overflows"))
                    continue
                new_row[column] = round(replaced_value, 6)
                replaced += 1
                affected_rows.append(dict(detail, after=new_row[column]))
                if unit_column:
                    new_row[unit_column] = canonical_unit
                out.append(new_row)
                lineage[new_row["_id"]] = [row["_id"]]
                continue
            flagged += 1
            marked = dict(row.get(values.ANOMALIES_KEY) or {})
            marked[column] = {"kind": values.KIND_NONFINITE, "raw": raw,
                              "stage": "after_conversion", "unit": unit}
            new_row[values.ANOMALIES_KEY] = marked
            affected_rows.append(dict(detail, after=raw, pending=True))
            if unit_column:
                new_row[unit_column] = canonical_unit
            out.append(new_row)
            lineage[new_row["_id"]] = [row["_id"]]
            continue

        converted_value = round(converted_value, 6)
        new_row[column] = converted_value
        converted += 1
        if unit != canonical_unit:
            affected_rows.append({
                "row_id": row["_id"], "column": column,
                "before": raw, "after": converted_value, "unit": unit,
            })
        if unit_column:
            new_row[unit_column] = canonical_unit
        out.append(new_row)
        lineage[new_row["_id"]] = [row["_id"]]

    problems = []
    if unknown_units:
        units = ", ".join(sorted(unknown_units))
        problems.append(
            f"column '{column}' has {sum(unknown_units.values())} row(s) "
            f"with unknown unit(s): {units}"
        )
    if unresolved:
        details = "; ".join(
            f"{item['row_id']}={item['before']!r}({values.describe_kind(item['kind'])})"
            for item in unresolved[:10]
        )
        more = "" if len(unresolved) <= 10 else f" ... (+{len(unresolved) - 10} more)"
        problems.append(
            f"column '{column}' has {len(unresolved)} unresolved value(s) "
            f"with no matching anomaly policy: {details}{more}"
        )
    if problems:
        raise ValueError("; ".join(problems))

    stats = {
        "column": column,
        "canonical_unit": canonical_unit,
        "converted_rows": converted,
        "missing_cells": counters[values.KIND_MISSING],
        "invalid_text_cells": counters[values.KIND_INVALID],
        "nonfinite_cells": counters[values.KIND_NONFINITE],
        "rows_flagged": flagged,
        "rows_dropped": dropped,
        "rows_replaced": replaced,
        "mixed_units": sorted(factors),
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
