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
    """Validate per-issue policies.

    Shape: {issue: {"action": ..., "replacement": <finite number>}}.
    """
    raw_policies = raw_policies or {}
    if not isinstance(raw_policies, dict):
        raise ValueError("policies must be an object keyed by issue kind")
    policies = {}
    for issue in issues:
        entry = raw_policies.get(issue, {"action": default_action})
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
        policies[issue] = {"action": action, "replacement": replacement}
    return policies


VALID_ACTIONS = ("error", "flag", "drop", "replace")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip() != ""]
    text = str(value).strip()
    return [text] if text else []


def normalize_rule_entry(entry, issue=None, default_action="error"):
    """Validate one (column, issue, source) rule entry.

    A rule may additionally narrow its scope with:

    * ``value_matches``: str | list[str] - only cells whose raw text
      equals one of these tokens (e.g. ["ERR", "ERROR"]) trigger it;
    * ``source_column`` / ``sources``: the rule only applies when the
      named column carries one of the given values, so two different
      sources of the same illegal text can be replaced for one source
      and dropped for the other.

    Returns a normalized dict; raises ValueError on malformed input.
    """
    if not isinstance(entry, dict):
        raise ValueError("rule entry must be an object")
    action = entry.get("action", default_action)
    if action not in VALID_ACTIONS:
        known = ", ".join(sorted(VALID_ACTIONS))
        raise ValueError(
            f"rule has unknown action '{action}' (known: {known})"
        )
    replacement = entry.get("replacement")
    if action == "replace":
        parsed = parse_number(replacement)
        if parsed is None or not math.isfinite(parsed):
            raise ValueError(
                f"rule needs a finite numeric replacement "
                f"(got {replacement!r}); bad values are never replaced by 0"
            )
        replacement = parsed
    rule = {
        "issue": issue or entry.get("issue"),
        "action": action,
        "replacement": replacement,
        "value_matches": _as_list(entry.get("value_matches")),
        "source_column": (str(entry["source_column"]).strip()
                          if entry.get("source_column") not in (None, "")
                          else None),
        "sources": _as_list(entry.get("sources")),
        "label": str(entry.get("label", "") or ""),
    }
    if not rule["issue"]:
        raise ValueError("rule entry needs an issue kind")
    if rule["sources"] and not rule["source_column"]:
        raise ValueError(
            f"rule for '{rule['issue']}' narrows by sources but no "
            "source_column was given"
        )
    return rule


def normalize_column_rules(raw, issues, default_action="error"):
    """Validate the per-column rule matrix.

    Accepted shapes (both may be mixed):

    * legacy ``{issue: {action, replacement}}`` policies;
    * ``{column: [ {issue, action, replacement?, value_matches?,
                    source_column?, sources?}, ... ]}`` rule lists.

    Returns ``{column: [normalized_rule, ...]}`` plus a "*" key holding
    legacy issue defaults. Rules are returned in definition order; the
    first matching rule wins.
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError("column rules must be an object")
    result = {}
    for key, entry in raw.items():
        if key in issues and isinstance(entry, dict) and "rules" not in entry:
            # Legacy issue-level default policy.
            normalized = normalize_policies({key: entry}, issues,
                                            default_action)[key]
            result.setdefault("*", []).append(
                {"issue": key, "action": normalized["action"],
                 "replacement": normalized["replacement"],
                 "value_matches": [], "source_column": None,
                 "sources": [], "label": ""})
            continue
        if isinstance(entry, dict) and "rules" in entry:
            entry = entry["rules"]
        if not isinstance(entry, list):
            raise ValueError(
                f"rules for column '{key}' must be a list of rule entries"
            )
        rules = []
        for item in entry:
            rule = normalize_rule_entry(item, default_action=default_action)
            if rule["issue"] not in issues:
                known = ", ".join(issues)
                raise ValueError(
                    f"rule for column '{key}' has unknown issue "
                    f"'{rule['issue']}' (known: {known})"
                )
            rules.append(rule)
        result.setdefault(str(key), []).extend(rules)
    return result


def resolve_rule(column_rules, column, issue, row, raw_value):
    """Pick the first matching rule for a cell, else the issue default.

    Per-column rules take precedence over legacy issue defaults; within
    one list the first rule whose value/source scope matches wins, so
    specific rules must be listed before generic ones.
    """
    candidates = list(column_rules.get(column, []))
    candidates.extend(column_rules.get("*", []))
    fallback = {"action": "error", "replacement": None}
    generic_default = None
    for rule in candidates:
        if rule["issue"] != issue:
            continue
        if rule["value_matches"]:
            if str(raw_value).strip() not in rule["value_matches"]:
                continue
        if rule["source_column"]:
            source_value = str(row.get(rule["source_column"]) or "").strip()
            if rule["sources"] and source_value not in rule["sources"]:
                continue
        if not rule["value_matches"] and not (rule["source_column"]
                                              and rule["sources"]):
            generic_default = rule
            continue
        return rule
    return generic_default or fallback


def optional_bound(params, key):
    value = params.get(key)
    if value is None or value == "":
        return None
    bound = parse_number(value)
    if bound is None or not math.isfinite(bound):
        raise ValueError(f"{key} must be a finite number")
    return bound
