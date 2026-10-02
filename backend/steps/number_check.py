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
from ..decisions import resolve_decision, rule_fingerprint
from .numbers import (ISSUE_LABELS, classify_number, count_action,
                      normalize_policies, optional_bound, resolve_policy,
                      summarise_actions)

ISSUES = ("missing", "illegal", "nonfinite", "out_of_range")


def apply(rows, params, context=None):
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
    raw_policies = dict(raw_policies)
    raw_policies.setdefault("missing", {"action": "flag"})
    policies = normalize_policies(raw_policies, ISSUES,
                                  default_action="error")
    source_column = params.get("source_column")
    manual_decisions = (context or {}).get("manual_decisions") or []

    counts = {issue: {} for issue in ISSUES}
    fingerprints = {}
    rule_keys = {}
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
            policy, scope, exception = resolve_decision(
                policies, category, row, col, "number_check",
                source_column=source_column,
                manual_decisions=manual_decisions)
            rule_keys[f"{row['_id']}|{col}|number_check|{category}"] = \
                rule_fingerprint(
                    col, category, "number_check",
                    resolve_policy(policies, category, policy.get("source")))
            action = policy["action"]
            if exception is not None:
                fingerprints[exception.get("id")] = rule_fingerprint(
                    col, category, "number_check", resolve_policy(
                        policies, category, policy.get("source")))
            count_action(counts, category, policy.get("source"), action)
            detail = {
                "row_id": row["_id"], "column": col,
                "stage": "number_check", "issue": category,
                "original_value": raw_value, "action": action,
                "source": policy.get("source"),
                "decision_scope": scope,
                "manual": scope == "manual",
                "exception_id": exception.get("id") if exception else None,
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

    source_summary = summarise_actions(counts, ISSUES)
    stats = {
        "columns": sorted(columns),
        "min_value": min_value,
        "max_value": max_value,
        "source_column": source_column,
        "issues": {label_text: info["total"]
                   for label_text, info in source_summary.items()},
        "issue_actions": {label_text: info["actions"]
                           for label_text, info in source_summary.items()},
        "issue_actions_by_source": source_summary,
        "rows_flagged": flagged_rows,
        "rows_dropped": dropped_rows,
        "cells_replaced": replaced_cells,
        "affected_rows": affected_rows,
        "rule_fingerprints": fingerprints,
        "current_rule_fingerprints": rule_keys,
    }
    return out, lineage, stats
