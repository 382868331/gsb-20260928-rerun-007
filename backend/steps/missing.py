"""Missing-value handling strategy.

params:
  columns: list[str]        # columns to handle; empty = all columns
  strategy: "drop_row" | "fill_constant" | "fill_mean" | "fill_median" | "fill_mode"
  fill_value: any           # required for fill_constant

Only genuinely missing cells are handled here. Illegal text and
non-finite values are left untouched (they belong to validate_numbers /
unit_convert policies) and never participate in mean/median fills.
Cells parked as "pending review" are left exactly as they were.
"""
from statistics import mean, median

from . import values


def _is_missing(row, col):
    marked = (row.get(values.ANOMALIES_KEY) or {}).get(col)
    if marked:
        return False
    kind, _, _ = values.classify(row.get(col))
    return kind == values.KIND_MISSING


def _finite_number(row, col):
    marked = (row.get(values.ANOMALIES_KEY) or {}).get(col)
    if marked:
        return None
    kind, number, _ = values.classify(row.get(col))
    return number if kind == values.KIND_FINITE else None


def apply(rows, params):
    strategy = params.get("strategy", "drop_row")
    columns = params.get("columns") or sorted(
        {key for row in rows for key in row if key != "_id"}
    )
    fill_value = params.get("fill_value")

    if strategy == "fill_constant":
        if fill_value is None or (
                isinstance(fill_value, str) and not fill_value.strip()):
            raise ValueError(
                "fill_constant needs an explicit non-empty 'fill_value' "
                "(missing values must not silently become empty or zero)")

    target_columns = set(columns)

    fills = {}
    if strategy == "fill_mean":
        for col in columns:
            vals = [_finite_number(row, col) for row in rows]
            vals = [v for v in vals if v is not None]
            if vals:
                fills[col] = round(mean(vals), 6)
    elif strategy == "fill_median":
        for col in columns:
            vals = [_finite_number(row, col) for row in rows]
            vals = [v for v in vals if v is not None]
            if vals:
                fills[col] = median(vals)
    elif strategy == "fill_mode":
        for col in columns:
            counts = {}
            for row in rows:
                if not _is_missing(row, col) and not (
                        row.get(values.ANOMALIES_KEY) or {}).get(col):
                    value = row.get(col)
                    counts[value] = counts.get(value, 0) + 1
            if counts:
                fills[col] = max(counts, key=lambda k: (counts[k], str(k)))

    affected = 0
    dropped = 0
    filled = 0
    affected_rows = []
    out = []
    lineage = {}

    for row in rows:
        missing_here = [col for col in target_columns if _is_missing(row, col)]
        affected += len(missing_here)
        if missing_here and strategy == "drop_row":
            dropped += 1
            affected_rows.append({
                "row_id": row["_id"],
                "columns": missing_here,
                "action": "drop_row",
            })
            continue
        new_row = dict(row)
        for col in missing_here:
            if strategy == "fill_constant":
                new_row[col] = fill_value
                filled += 1
                affected_rows.append({
                    "row_id": row["_id"], "column": col,
                    "before": row.get(col), "after": fill_value,
                    "action": "fill_constant",
                })
            elif strategy in ("fill_mean", "fill_median", "fill_mode"):
                if col in fills:
                    new_row[col] = fills[col]
                    filled += 1
                    affected_rows.append({
                        "row_id": row["_id"], "column": col,
                        "before": row.get(col), "after": fills[col],
                        "action": strategy,
                    })
                # No fill available (all missing / non-numeric): leave as-is
        out.append(new_row)
        lineage[new_row["_id"]] = [row["_id"]]

    stats = {
        "strategy": strategy,
        "columns": sorted(target_columns),
        "missing_cells": affected,
        "rows_dropped": dropped,
        "cells_filled": filled,
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
