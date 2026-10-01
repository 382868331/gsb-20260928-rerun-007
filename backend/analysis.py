"""Rule-impact analysis and version comparison.

Both helpers operate on in-memory row sets so they can power the
preview API without publishing anything.
"""
from .steps.numbers import (
    ISSUE_LABELS, classify_number, normalize_column_rules, optional_bound,
    resolve_rule,
)


def _scan_number_rows(rows, columns, params, step_type):
    min_value = optional_bound(params, "min_value")
    max_value = optional_bound(params, "max_value")
    raw = params.get("policies") or {}
    issues = ("missing", "illegal", "nonfinite", "out_of_range")
    column_rules = normalize_column_rules(raw, issues, default_action="error")
    found = []
    for row in rows:
        for col in columns:
            raw_value = row.get(col)
            category, _ = classify_number(raw_value, min_value, max_value)
            if category == "ok":
                continue
            rule = resolve_rule(column_rules, col, category, row, raw_value)
            found.append({
                "row_id": row["_id"], "column": col, "issue": category,
                "issue_label": ISSUE_LABELS[category],
                "original_value": raw_value,
                "action": rule["action"],
                "replacement": rule.get("replacement"),
                "rule_label": rule.get("label") or None,
                "source_column": rule.get("source_column"),
                "source_value": (row.get(rule["source_column"])
                                 if rule.get("source_column") else None),
                "step": step_type,
                "row": row,
            })
    return found


def rule_impact(old_params, new_params, rows, step_type="number_check",
                columns=None, exceptions=None):
    """Diff two parameter sets over the same rows.

    Returns affected old records (decision changed between rule sets) and
    new records (rows that the new rules handle but the old ones did not
    name explicitly). Manual exceptions that conflict with the new rule
    are listed so the caller can ask the user whether to keep them.
    """
    columns = columns or sorted(
        {key for row in rows for key in row if not key.startswith("_")})
    old_hits = {h["row_id"] + "|" + h["column"] + "|" + h["issue"]: h
                for h in _scan_number_rows(rows, columns, old_params,
                                          step_type)}
    new_hits = {h["row_id"] + "|" + h["column"] + "|" + h["issue"]: h
                for h in _scan_number_rows(rows, columns, new_params,
                                          step_type)}
    changed = []
    for key, new_hit in new_hits.items():
        old_hit = old_hits.get(key)
        if old_hit is None:
            continue
        if (old_hit["action"] != new_hit["action"] or
                old_hit.get("replacement") != new_hit.get("replacement")):
            changed.append({
                "row_id": new_hit["row_id"],
                "column": new_hit["column"],
                "issue": new_hit["issue"],
                "issue_label": new_hit["issue_label"],
                "original_value": new_hit["original_value"],
                "old_action": old_hit["action"],
                "new_action": new_hit["action"],
                "old_replacement": old_hit.get("replacement"),
                "new_replacement": new_hit.get("replacement"),
            })
    added = []
    for key, hit in new_hits.items():
        old_hit = old_hits.get(key)
        newly_named = old_hit is None
        generic_before = (
            old_hit is not None
            and not old_hit.get("rule_label")
            and not old_hit.get("source_column")
            and (hit.get("rule_label") or hit.get("source_column")))
        if newly_named or generic_before:
            added.append({k: hit[k] for k in (
                "row_id", "column", "issue", "issue_label",
                "original_value", "action", "replacement",
                "rule_label", "source_column", "source_value")})

    conflicting_exceptions = []
    if exceptions:
        from .exceptions import active_map
        for key, item in active_map(exceptions).items():
            row_id = item["row_id"]
            scope_parts = item["scope"].split(":")
            if len(scope_parts) < 4 or scope_parts[0] != step_type:
                continue
            _step, col, _stage, issue = scope_parts[:4]
            hit_key = f"{row_id}|{col}|{issue}"
            hit = new_hits.get(hit_key)
            if hit and hit["action"] != item["action"]:
                conflicting_exceptions.append({
                    "row_id": row_id, "column": col, "issue": issue,
                    "manual_action": item["action"],
                    "rule_action": hit["action"],
                    "reason": item.get("reason", ""),
                })
    return {
        "changed_decisions": changed,
        "newly_handled": added,
        "conflicting_exceptions": conflicting_exceptions,
    }


def version_diff(old_version, new_version, old_rows=None, new_rows=None):
    """Compare two versions, attributing differences to cause.

    Causes: ``data_added`` (new original row ids), ``rule_changed``
    (same row id, different value because of differing step actions) and
    ``manual`` (the step action detail is marked manual).
    """
    old_rows = old_rows or old_version.get("rows", [])
    new_rows = new_rows or new_version.get("rows", [])
    old_by_id = {r["_id"]: r for r in old_rows}
    new_by_id = {r["_id"]: r for r in new_rows}
    old_origins = set(old_by_id)
    new_origins = set()
    v0_origins = None
    for rid, origins in new_version.get("lineage", {}).items():
        new_origins.update(origins)

    manual_rows = set()
    rule_rows = {}
    for report in new_version.get("step_reports", []):
        for item in report.get("stats", {}).get("affected_rows", []):
            rid = item.get("row_id")
            if item.get("manual"):
                manual_rows.add(rid)
            elif item.get("decision_source") == "rule":
                rule_rows.setdefault(rid, []).append(item)

    data_added = sorted(new_origins - old_origins - manual_rows)
    data_removed = sorted(
        origin for origin in old_origins - new_origins
        if origin in old_by_id and origin not in manual_rows)

    value_changed = []
    for rid, row in new_by_id.items():
        if rid not in old_by_id:
            continue
        before = old_by_id[rid]
        changed_cols = [k for k, v in row.items()
                        if not k.startswith("_") and before.get(k) != v]
        review_added = (set(row.get("_review", []) or []) -
                        set(before.get("_review", []) or [])) \
                       if rid in manual_rows else set()
        if changed_cols or review_added:
            value_changed.append({
                "row_id": rid,
                "columns": sorted(set(changed_cols) | {
                    tag.split(":", 1)[0] for tag in review_added}),
                "cause": "manual" if rid in manual_rows else "rule_changed",
            })
    # Rows absent from the old version but present now are data
    # additions when a real published rule version excluded them too
    # (origins differ), otherwise they are rows restored by a manual
    # exception rather than newly arrived data.
    dropped_rows = sorted(
        rid for rid in old_by_id
        if rid not in new_by_id and rid not in manual_rows)
    restored_rows = sorted(
        rid for rid in manual_rows if rid in new_by_id)
    readded_rows = []
    return {
        "data_added": data_added,
        "data_removed": data_removed,
        "value_changed": value_changed,
        "dropped_rows": dropped_rows,
        "readded_rows": readded_rows,
        "restored_rows": restored_rows,
        "manual_rows": sorted(manual_rows),
        "rule_action_rows": sorted(rule_rows),
    }
