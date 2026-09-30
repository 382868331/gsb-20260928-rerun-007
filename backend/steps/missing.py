"""Missing-value handling strategy.

params:
  columns: list[str]        # columns to handle; empty = all columns
  strategy: "drop_row" | "fill_constant" | "fill_mean" | "fill_median" | "fill_mode"
  fill_value: any           # required for fill_constant
"""
import math
from statistics import mean, median

from .numbers import is_missing, parse_number


def _is_missing(value):
    return is_missing(value)


def _as_number(value):
    """Finite numbers only: infinity text is not a fillable measurement."""
    number = parse_number(value)
    if number is not None and math.isfinite(number):
        return number
    return None


def apply(rows, params):
    strategy = params.get("strategy", "drop_row")
    columns = params.get("columns") or sorted(
        {key for row in rows for key in row if not key.startswith("_")}
    )
    fill_value = params.get("fill_value")

    target_columns = set(columns)

    numeric_columns = {col for col in columns
                       if any(_as_number(row.get(col)) is not None
                              for row in rows)}

    fills = {}
    if strategy == "fill_mean":
        for col in columns:
            vals = [_as_number(row.get(col)) for row in rows]
            vals = [v for v in vals if v is not None]
            if vals:
                fills[col] = round(mean(vals), 6)
    elif strategy == "fill_median":
        for col in columns:
            vals = [_as_number(row.get(col)) for row in rows]
            vals = [v for v in vals if v is not None]
            if vals:
                fills[col] = median(vals)
    elif strategy == "fill_mode":
        for col in columns:
            counts = {}
            for row in rows:
                value = row.get(col)
                if not _is_missing(value):
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
        missing_here = [col for col in target_columns if _is_missing(row.get(col))]
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
            new_row["_review"] = [tag for tag in new_row.get("_review", [])
                                   if not tag.startswith(f"{col}:")]
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
