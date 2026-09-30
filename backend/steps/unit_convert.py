"""Unit normalisation for a measurement column.

params:
  column: str            # value column, e.g. "temperature"
  unit_column: str|None  # column carrying the source unit; per-row units
  rules: {unit: factor | {"factor": f, "offset": b}}
    # canonical = raw * factor + offset (e.g. Fahrenheit to Celsius)
  canonical_unit: str    # target unit label, e.g. "C"

Conversion is linear: canonical = raw * factor. Rows whose unit is not
covered by rules raise ValueError so a half-published result is impossible.
"""

def _as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}


def _is_missing(value):
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING_TOKENS
    )


def apply(rows, params):
    column = params["column"]
    unit_column = params.get("unit_column")
    rules = params.get("rules") or {}
    canonical_unit = params["canonical_unit"]

    factors = {}
    for unit, rule in rules.items():
        if isinstance(rule, dict):
            factors[str(unit).strip()] = (
                float(rule.get("factor", 1.0)), float(rule.get("offset", 0.0)))
        else:
            factors[str(unit).strip()] = (float(rule), 0.0)
    factors.setdefault(canonical_unit, (1.0, 0.0))

    converted = 0
    unknown_units = {}
    non_numeric = []
    affected_rows = []
    out = []
    lineage = {}

    for row in rows:
        unit = canonical_unit
        if unit_column:
            raw_unit = row.get(unit_column)
            unit = str(raw_unit).strip() if raw_unit is not None else canonical_unit
        factor_offset = factors.get(unit)
        if factor_offset is None:
            unknown_units[unit] = unknown_units.get(unit, 0) + 1
            continue

        new_row = dict(row)
        number = _as_number(row.get(column))
        factor, offset = factor_offset
        if number is None:
            if not _is_missing(row.get(column)):
                non_numeric.append(row["_id"])
            # missing value: leave untouched for a later missing-values step
        else:
            converted_value = round(number * factor + offset, 6)
            new_row[column] = converted_value
            converted += 1
            if unit != canonical_unit:
                affected_rows.append({
                    "row_id": row["_id"],
                    "column": column,
                    "before": row.get(column),
                    "after": converted_value,
                    "unit": unit,
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
    if non_numeric:
        problems.append(
            f"column '{column}' has {len(non_numeric)} non-numeric value(s)"
        )
    if problems:
        raise ValueError("; ".join(problems))

    stats = {
        "column": column,
        "canonical_unit": canonical_unit,
        "converted_rows": converted,
        "mixed_units": sorted(factors),
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
