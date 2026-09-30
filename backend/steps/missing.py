"""Missing-value handling strategy.

params:
  columns: list[str]        # columns to handle; empty = all columns
  strategy: "drop_row" | "fill_constant" | "fill_mean" | "fill_median" | "fill_mode"
  fill_value: any           # required for fill_constant
"""
from statistics import mean, median


MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a"}


def _is_missing(value):
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING_TOKENS
    )


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


def apply(rows, params):
    strategy = params.get("strategy", "drop_row")
    columns = params.get("columns") or sorted(
        {key for row in rows for key in row if key != "_id"}
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
    out = []
    lineage = {}
    effects = []

    for row in rows:
        missing_here = [col for col in target_columns if _is_missing(row.get(col))]
        affected += len(missing_here)
        if missing_here and strategy == "drop_row":
            dropped += 1
            effects.append({
                "row_id": row["_id"], "action": "dropped",
                "detail": {"strategy": strategy,
                           "missing_columns": missing_here},
            })
            continue
        new_row = dict(row)
        for col in missing_here:
            if strategy == "fill_constant":
                new_row[col] = fill_value
                filled += 1
                effects.append({
                    "row_id": row["_id"], "action": "filled",
                    "detail": {"strategy": strategy, "column": col,
                               "value": fill_value},
                })
            elif strategy in ("fill_mean", "fill_median", "fill_mode"):
                if col in fills:
                    new_row[col] = fills[col]
                    filled += 1
                    effects.append({
                        "row_id": row["_id"], "action": "filled",
                        "detail": {"strategy": strategy, "column": col,
                                   "value": fills[col]},
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
        "affected_row_ids": sorted({e["row_id"] for e in effects}),
        "effects": effects,
    }
    return out, lineage, stats
