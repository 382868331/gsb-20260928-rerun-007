"""Unit normalisation for a measurement column.

params:
  column: str            # value column, e.g. "temperature"
  unit_column: str|None  # column carrying the source unit; per-row units
  rules: {unit: factor | {"factor": f, "offset": b}}
    # canonical = raw * factor + offset (e.g. Fahrenheit to Celsius)
  canonical_unit: str    # target unit label, e.g. "C"
  policies: {"missing"|"illegal"|"nonfinite"|"out_of_range":
               {"action": "error"|"flag"|"drop"|"replace",
                "replacement": number}}  # handling of bad RAW values
  post_policies: same shape, applied to values AFTER conversion, where the
               relevant issues are "nonfinite" and "out_of_range"
  min_value / max_value: finite raw-value bounds (before conversion)
  post_min_value / post_max_value: finite canonical-value bounds

Validity is checked both before and after conversion: a raw "Infinity"
text is caught up front, and a finite raw value that overflows or leaves
the allowed range after scaling is caught afterwards. Rows are never
silently turned into 0; every rejected row records its original value.
"""
from ..decisions import resolve_decision, rule_fingerprint
from .numbers import (ISSUE_LABELS, classify_number, count_action,
                      normalize_policies, optional_bound, resolve_policy,
                      summarise_actions)

PRE_ISSUES = ("missing", "illegal", "nonfinite", "out_of_range")
POST_ISSUES = ("nonfinite", "out_of_range")


def _rule_factors(rules, canonical_unit):
    factors = {}
    for unit, rule in (rules or {}).items():
        if isinstance(rule, dict):
            factor = float(rule.get("factor", 1.0))
            offset = float(rule.get("offset", 0.0))
        else:
            factor, offset = float(rule), 0.0
        if factor == 0.0 or factor != factor or factor in (
                float("inf"), float("-inf")):
            raise ValueError(f"unit rule for '{unit}' needs a nonzero finite factor")
        if offset != offset or offset in (float("inf"), float("-inf")):
            raise ValueError(f"unit rule for '{unit}' needs a finite offset")
        factors[str(unit).strip()] = (factor, offset)
    factors.setdefault(canonical_unit, (1.0, 0.0))
    return factors


def apply(rows, params, context=None):
    column = params["column"]
    unit_column = params.get("unit_column")
    canonical_unit = params["canonical_unit"]
    factors = _rule_factors(params.get("rules"), canonical_unit)

    min_value = optional_bound(params, "min_value")
    max_value = optional_bound(params, "max_value")
    post_min = optional_bound(params, "post_min_value")
    post_max = optional_bound(params, "post_max_value")
    # Missing values are left for a later missing-values step by default;
    # everything else aborts so bad numbers can never reach a result.
    raw_pre = dict(params.get("policies") or {})
    raw_pre.setdefault("missing", {"action": "flag"})
    policies = normalize_policies(raw_pre, PRE_ISSUES, default_action="error")
    post_policies = normalize_policies(
        params.get("post_policies"), POST_ISSUES, default_action="error")
    source_column = params.get("source_column")
    manual_decisions = (context or {}).get("manual_decisions") or []

    converted = 0
    unknown_units = {}
    counts = {"pre": {issue: 0 for issue in PRE_ISSUES},
              "post": {issue: 0 for issue in POST_ISSUES}}
    actions_by_issue = {"pre": {}, "post": {}}
    affected_rows = []
    out = []
    lineage = {}
    fingerprints = {}
    rule_keys = {}

    def note(stage, issue, action):
        counts[stage][issue] += 1
        actions_by_issue[stage][issue].setdefault(action, 0)
        actions_by_issue[stage][issue][action] += 1

    for row in rows:
        unit = canonical_unit
        if unit_column:
            raw_unit = row.get(unit_column)
            unit = (str(raw_unit).strip() if raw_unit is not None
                    else canonical_unit)
        factor_offset = factors.get(unit)
        if factor_offset is None:
            unknown_units[unit] = unknown_units.get(unit, 0) + 1
            continue

        raw_value = row.get(column)
        category, number = classify_number(raw_value, min_value, max_value)
        new_row = dict(row)

        if category != "ok":
            policy, scope, exception = resolve_decision(
                policies, category, row, column, "pre_convert",
                source_column=source_column,
                manual_decisions=manual_decisions)
            if exception is not None:
                fingerprints[exception.get("id")] = rule_fingerprint(
                    column, category, "pre_convert", resolve_policy(
                        policies, category, policy.get("source")))
            counts["pre"][category] += 1
            rule_keys[f"{row['_id']}|{column}|pre_convert|{category}"] = \
                rule_fingerprint(
                    column, category, "pre_convert", resolve_policy(
                        policies, category, policy.get("source")))
            count_action(actions_by_issue["pre"], category,
                         policy.get("source"), policy["action"])
            detail = {
                "row_id": row["_id"], "column": column,
                "stage": "pre_convert", "issue": category,
                "original_value": raw_value, "unit": unit,
                "action": policy["action"],
                "source": policy.get("source"),
                "decision_scope": scope,
                "manual": scope == "manual",
                "exception_id": exception.get("id") if exception else None,
            }
            if policy["action"] == "error":
                raise ValueError(
                    f"column '{column}' row {row['_id']}: "
                    f"{ISSUE_LABELS[category]}/"
                    f"{'non-numeric value' if category == 'illegal' else category}"
                    f"（原值 {raw_value!r}）；"
                    "可在策略中选择保留待核对、排除或替代"
                )
            if policy["action"] == "drop":
                detail["action"] = "drop_row"
                affected_rows.append(detail)
                continue
            if policy["action"] == "replace":
                # Replacement is expressed in the canonical unit.
                new_row[column] = policy["replacement"]
                new_row["_review"] = [tag for tag in new_row.get("_review", [])
                                       if not tag.startswith(f"{column}:")]
                detail["after"] = policy["replacement"]
                affected_rows.append(detail)
            else:  # flag: keep the ORIGINAL value, mark for review
                review = list(new_row.get("_review", []))
                review.append(f"{column}:{category}")
                new_row["_review"] = review
                detail["flagged"] = True
                affected_rows.append(detail)
            if unit_column:
                new_row[unit_column] = canonical_unit
            out.append(new_row)
            lineage[new_row["_id"]] = [row["_id"]]
            continue

        factor, offset = factor_offset
        converted_value = number * factor + offset
        post_category = "ok"
        if converted_value != converted_value or converted_value in (
                float("inf"), float("-inf")):
            post_category = "nonfinite"
        elif ((post_min is not None and converted_value < post_min) or
              (post_max is not None and converted_value > post_max)):
            post_category = "out_of_range"

        if post_category != "ok":
            policy, scope, exception = resolve_decision(
                post_policies, post_category, row, column, "post_convert",
                source_column=source_column,
                manual_decisions=manual_decisions)
            if exception is not None:
                fingerprints[exception.get("id")] = rule_fingerprint(
                    column, post_category, "post_convert", resolve_policy(
                        post_policies, post_category, policy.get("source")))
            counts["post"][post_category] += 1
            rule_keys[f"{row['_id']}|{column}|post_convert|"
                      f"{post_category}"] = rule_fingerprint(
                column, post_category, "post_convert", resolve_policy(
                    post_policies, post_category, policy.get("source")))
            count_action(actions_by_issue["post"], post_category,
                         policy.get("source"), policy["action"])
            detail = {
                "row_id": row["_id"], "column": column,
                "stage": "post_convert", "issue": post_category,
                "original_value": raw_value, "converted_value": converted_value,
                "unit": unit, "action": policy["action"],
                "source": policy.get("source"),
                "decision_scope": scope,
                "manual": scope == "manual",
                "exception_id": exception.get("id") if exception else None,
            }
            if policy["action"] == "error":
                raise ValueError(
                    f"column '{column}' row {row['_id']}: 换算后"
                    f"{ISSUE_LABELS[post_category]}（原值 {raw_value!r} {unit} "
                    f"→ {converted_value}）"
                )
            if policy["action"] == "drop":
                detail["action"] = "drop_row"
                affected_rows.append(detail)
                continue
            if policy["action"] == "replace":
                converted_value = policy["replacement"]
                new_row["_review"] = [tag for tag in new_row.get("_review", [])
                                       if not tag.startswith(f"{column}:")]
                detail["after"] = converted_value
                affected_rows.append(detail)
            else:  # flag: keep the converted value but mark it
                review = list(new_row.get("_review", []))
                review.append(f"{column}:{post_category}")
                new_row["_review"] = review
                detail["flagged"] = True
                affected_rows.append(detail)
        else:
            converted_value = round(converted_value, 6)
            if unit != canonical_unit:
                affected_rows.append({
                    "row_id": row["_id"], "column": column,
                    "before": raw_value, "after": converted_value,
                    "unit": unit, "action": "convert",
                })

        new_row[column] = converted_value
        converted += 1
        if unit_column:
            new_row[unit_column] = canonical_unit
        out.append(new_row)
        lineage[new_row["_id"]] = [row["_id"]]

    if unknown_units:
        units = ", ".join(sorted(unknown_units))
        raise ValueError(
            f"column '{column}' has {sum(unknown_units.values())} row(s) "
            f"with unknown unit(s): {units}"
        )

    def _summary(stage_counts):
        return {ISSUE_LABELS[k]: v for k, v in stage_counts.items() if v}

    stats = {
        "column": column,
        "canonical_unit": canonical_unit,
        "source_column": source_column,
        "converted_rows": converted,
        "mixed_units": sorted(factors),
        "pre_convert_issues": _summary(counts["pre"]),
        "post_convert_issues": _summary(counts["post"]),
        "issue_actions": {
            stage: {label_text: info["actions"]
                    for label_text, info in summarise_actions(
                        by_issue,
                        PRE_ISSUES if stage == "pre_convert" else POST_ISSUES
                    ).items()}
            for stage, by_issue in (
                ("pre_convert", actions_by_issue["pre"]),
                ("post_convert", actions_by_issue["post"]))
            if any(by_issue.values())
        },
        "issue_actions_by_source": {
            "pre_convert": summarise_actions(
                actions_by_issue["pre"], PRE_ISSUES),
            "post_convert": summarise_actions(
                actions_by_issue["post"], POST_ISSUES),
        },
        "affected_rows": affected_rows,
        "rule_fingerprints": fingerprints,
        "current_rule_fingerprints": rule_keys,
    }
    return out, lineage, stats
