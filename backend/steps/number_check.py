"""Numeric validity check for measurement columns.

Distinguishes four data problems per cell and applies a separately
configured policy to each:

* missing      - empty / NA tokens
* illegal      - text that is not a number (e.g. "ERR")
* nonfinite    - "Infinity", "-inf", "nan" or non-finite float values
* out_of_range - finite value outside [min_value, max_value]

params:
  columns: list[str]   # columns to check
  min_value, max_value: finite bounds (optional)
  policies: {issue: {"action": "flag"|"drop"|"replace"|"error",
                      "replacement": number}}

Actions never invent a zero: ``replace`` requires an explicit finite
replacement, ``flag`` keeps the original value with a ``_review`` marker
and ``drop`` records the removed row with its original value for lineage.
"""
from .numbers import (ISSUE_LABELS, POLICY_LABELS, classify_number,
                      normalize_policies, optional_bound)

ISSUES = ("missing", "illegal", "nonfinite", "out_of_range")


def apply(rows, params):
    columns = params.get("columns") or sorted(
        {key for row in rows for key in row if not key.startswith("_")}
    )
    if not columns:
        raise ValueError("number_check needs at least one column")
    min_value = optional_bound(params, "min_value")
    max_value = optional_bound(params, "max_value")
    raw_policies = params.get("policies") or {}
    # Defaults: missing rows are kept for later review; genuinely bad
    # numbers stop the run instead of silently entering results.
    policies = normalize_policies(raw_policies, ISSUES,
                                  default_action="error")
    policies["missing"] = normalize_policies(
        raw_policies, ("missing",), default_action="flag")["missing"]

    counts = {issue: {} for issue in ISSUES}
    flagged_rows = 0
    dropped_rows = 0
    replaced_cells = 0
    affected_rows = []
    out = []
    lineage = {}

    for row in rows:
        new_row = dict(row)
        drop_row = False
        row_flags = []
        for col in columns:
            raw_value = row.get(col)
            category, _number = classify_number(
                raw_value, min_value, max_value)
            if category == "ok":
                continue
            policy = policies[category]
            action = policy["action"]
            counts[category].setdefault(action, 0)
            counts[category][action] += 1
            detail = {
                "row_id": row["_id"], "column": col,
                "stage": "number_check", "issue": category,
                "original_value": raw_value, "action": action,
            }
            if action == "error":
                raise ValueError(
                    f"column '{col}' row {row['_id']}: "
                    f"{ISSUE_LABELS[category]}/"
                    f"{'non-numeric value' if category == 'illegal' else category}"
                    f"（原值 {raw_value!r}）；"
                    "可在策略中选择保留待核对、排除或替代"
                )
            if action == "drop":
                detail["action"] = "drop_row"
                affected_rows.append(detail)
                drop_row = True
                continue
            if action == "replace":
                new_row[col] = policy["replacement"]
                new_row["_review"] = [tag for tag in new_row.get("_review", [])
                                      if not tag.startswith(f"{col}:")]
                detail["after"] = policy["replacement"]
                replaced_cells += 1
                affected_rows.append(detail)
            else:  # flag: original value stays, marker is added
                row_flags.append(f"{col}:{category}")
                detail["flagged"] = True
                affected_rows.append(detail)
        if drop_row:
            dropped_rows += 1
            continue
        if row_flags:
            review = list(new_row.get("_review", []))
            review.extend(row_flags)
            new_row["_review"] = review
            flagged_rows += 1
        out.append(new_row)
        lineage[new_row["_id"]] = [row["_id"]]

    stats = {
        "columns": sorted(columns),
        "min_value": min_value,
        "max_value": max_value,
        "issues": {ISSUE_LABELS[k]: sum(by_action.values())
                   for k, by_action in counts.items() if by_action},
        "issue_actions": {
            ISSUE_LABELS[issue]: {POLICY_LABELS[a]: n for a, n in actions.items()}
            for issue, actions in counts.items() if actions
        },
        "rows_flagged": flagged_rows,
        "rows_dropped": dropped_rows,
        "cells_replaced": replaced_cells,
        "affected_rows": affected_rows,
    }
    return out, lineage, stats
