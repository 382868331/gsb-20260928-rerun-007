"""Shared finite-number classification for cleaning steps.

Every numeric cell falls into exactly one category:

* ``missing``      - empty cell or an explicit missing token ("", NA, ...)
* ``illegal``      - text that cannot be parsed as a number at all
* ``nonfinite``    - parses to infinity/NaN (e.g. "Infinity", "inf") or
                     an actual non-finite float; never usable as measurement
* ``out_of_range`` - finite number outside an optional [min_value, max_value]
* ``ok``           - finite number inside the allowed range

The original raw value is always carried alongside the classification so
that rejected rows can be traced back to what the source actually said;
a bad value is never silently coerced to zero.
"""
import math

MISSING_TOKENS = {"", "na", "null", "none", "n/a"}

ISSUE_LABELS = {
    "missing": "缺失",
    "illegal": "非法文字",
    "nonfinite": "非有限数值（无穷/NaN）",
    "out_of_range": "超出有限范围",
}

POLICY_LABELS = {
    "error": "中止执行",
    "flag": "保留待核对",
    "drop": "排除该行",
    "replace": "使用替代值",
}


def is_missing(value):
    return value is None or (
        isinstance(value, str) and value.strip().lower() in MISSING_TOKENS
    )


def parse_number(value):
    """Parse a cell into a float, or None for missing/unparseable text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in MISSING_TOKENS:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def classify_number(value, min_value=None, max_value=None):
    """Return ``(category, number)``.

    ``number`` is None unless the category is ``ok`` or ``out_of_range``
    (the latter carries the finite raw number for diagnostics).
    """
    if is_missing(value):
        return "missing", None
    number = parse_number(value)
    if number is None:
        return "illegal", None
    if not math.isfinite(number):
        return "nonfinite", None
    if min_value is not None and number < min_value:
        return "out_of_range", number
    if max_value is not None and number > max_value:
        return "out_of_range", number
    return "ok", number


def normalize_policies(raw_policies, issues, default_action="error"):
    """Validate per-issue policies, optionally per source/batch.

    Global shape::

        {issue: {"action": ..., "replacement": <finite number>}}

    Source-specific overrides live under ``by_source`` so the same issue
    kind can be replaced for one source and dropped for another::

        {issue: {"action": "flag"},
         "by_source": {"batch-A": {issue: {"action": "drop"}}}}

    Every source override is validated up front; a bad override never
    silently falls back to the global policy.
    """
    raw_policies = raw_policies or {}
    if not isinstance(raw_policies, dict):
        raise ValueError("policies must be an object keyed by issue kind")
    policies = {}
    for issue in issues:
        policies[issue] = _validate_entry(
            issue, raw_policies.get(issue, {"action": default_action}),
            default_action)
    by_source_raw = raw_policies.get("by_source") or {}
    if by_source_raw and not isinstance(by_source_raw, dict):
        raise ValueError("policies.by_source must be an object keyed by source")
    by_source = {}
    for source, source_policies in by_source_raw.items():
        if not isinstance(source_policies, dict):
            raise ValueError(f"policies.by_source['{source}'] must be an object")
        validated = {}
        for issue, entry in source_policies.items():
            if issue not in policies:
                raise ValueError(
                    f"source '{source}' policy for unknown issue '{issue}'")
            validated[issue] = _validate_entry(issue, entry,
                                               entry.get("action",
                                                         default_action))
        by_source[str(source)] = validated
    if by_source:
        policies["by_source"] = by_source
    return policies


def _validate_entry(issue, entry, default_action):
    if not isinstance(entry, dict):
        raise ValueError(f"policy for '{issue}' must be an object")
    action = entry.get("action", default_action)
    if action not in POLICY_LABELS:
        known = ", ".join(sorted(POLICY_LABELS))
        raise ValueError(
            f"policy for '{issue}' has unknown action '{action}' "
            f"(known: {known})"
        )
    replacement = entry.get("replacement")
    if action == "replace":
        parsed = parse_number(replacement)
        if parsed is None or not math.isfinite(parsed):
            raise ValueError(
                f"policy for '{issue}' needs a finite numeric "
                f"replacement (got {replacement!r}); bad values are "
                "never replaced by 0"
            )
        replacement = parsed
    return {"action": action, "replacement": replacement}


def resolve_policy(policies, issue, source=None):
    """Resolve one issue's policy for one source/batch.

    A source-specific override always wins; otherwise the global policy
    applies. The result carries ``source`` and ``source_specific`` so
    reports can show which source actually made the decision.
    """
    by_source = (policies or {}).get("by_source") or {}
    override = by_source.get(str(source), {}).get(issue) if source else None
    policy = dict(override or policies[issue])
    policy["source"] = source
    policy["source_specific"] = override is not None
    return policy


def count_action(counts, issue, source, action):
    """Tally an action per issue *and* per source/batch.

    ``counts`` has shape {issue: {source: {action: n}}}; one source's
    "replace" is therefore never summed onto another source's "drop".
    """
    source_key = str(source) if source is not None else "_all"
    actions = counts.setdefault(issue, {}).setdefault(source_key, {})
    actions[action] = actions.get(action, 0) + 1


def summarise_actions(counts, issues):
    """Render per-issue/per-source action tallies for stats/reports."""
    summary = {}
    for issue in issues:
        by_source = counts.get(issue)
        if not by_source:
            continue
        per_source, totals = {}, {}
        for source, actions in by_source.items():
            labelled = {POLICY_LABELS.get(a, a): n for a, n in actions.items()}
            per_source[source] = labelled
            for action, n in actions.items():
                label = POLICY_LABELS.get(action, action)
                totals[label] = totals.get(label, 0) + n
        summary[ISSUE_LABELS[issue]] = {
            "total": sum(sum(a.values()) for a in by_source.values()),
            "actions": totals,
            "by_source": per_source,
        }
    return summary


def optional_bound(params, key):
    value = params.get(key)
    if value is None or value == "":
        return None
    bound = parse_number(value)
    if bound is None or not math.isfinite(bound):
        raise ValueError(f"{key} must be a finite number")
    return bound
