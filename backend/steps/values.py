"""Shared numeric validity classification.

Every numeric step distinguishes three clearly different problems:

* ``missing``    -- empty cell or a missing token such as ``N/A``;
* ``invalid``    -- present text that cannot be parsed as a number
                    (e.g. ``ERR``, ``oops``, ``true``);
* ``nonfinite``  -- a parseable value that escapes the finite range
                    (``inf``, ``-infinity``, ``NaN``), or the result of
                    an arithmetic conversion that overflowed to infinity.

Parsing ``"inf"``/``"nan"`` with :func:`float` would otherwise let
infinity leak into converted results, means and medians.
"""
import math

MISSING_TOKENS = frozenset({
    "", "na", "n/a", "null", "none",
    "\u7f3a\u5931", "\u5f85\u8865", "--", "-",
})

KIND_FINITE = "finite"
KIND_MISSING = "missing"
KIND_INVALID = "invalid"
KIND_NONFINITE = "nonfinite"

ANOMALY_KINDS = (KIND_MISSING, KIND_INVALID, KIND_NONFINITE)

POLICIES = ("flag", "drop", "replace")

# Per-cell marker for rows kept "pending review" (flag policy). The
# original column value is never silently turned into zero.
ANOMALIES_KEY = "_anomalies"


def classify(value):
    """Return ``(kind, number, raw)`` for a raw cell value."""
    raw = value
    if value is None:
        return KIND_MISSING, None, raw
    if isinstance(value, bool):
        return KIND_INVALID, None, raw
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return KIND_FINITE, number, raw
        return KIND_NONFINITE, None, raw
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in MISSING_TOKENS:
            return KIND_MISSING, None, raw
        try:
            number = float(text)
        except ValueError:
            return KIND_INVALID, None, raw
        if math.isfinite(number):
            return KIND_FINITE, number, raw
        return KIND_NONFINITE, None, raw
    return KIND_INVALID, None, raw


def finite_result(value):
    """Validate the output of a conversion/arithmetic expression."""
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def resolve_policy(kind, source, rules):
    """Find the configured rule for ``(kind, source)``.

    An exact source match wins; otherwise a wildcard rule (source
    omitted/empty/"*") is used. Returns the rule dict or ``None``.
    """
    wildcard = None
    for rule in rules:
        if rule.get("kind") != kind:
            continue
        rule_source = rule.get("source")
        if rule_source in (None, "", "*"):
            if wildcard is None:
                wildcard = rule
        elif str(rule_source).strip() == str(source):
            return rule
    return wildcard


def validate_rule(rule):
    """Validate one anomaly policy rule; return the parsed replacement."""
    if not isinstance(rule, dict):
        raise ValueError(f"anomaly rule must be an object, got {rule!r}")
    kind = rule.get("kind")
    if kind not in ANOMALY_KINDS:
        raise ValueError(
            f"anomaly rule kind must be one of {', '.join(ANOMALY_KINDS)}, "
            f"got {kind!r}"
        )
    action = rule.get("action")
    if action not in POLICIES:
        raise ValueError(
            f"anomaly rule action must be one of {', '.join(POLICIES)}, "
            f"got {action!r}"
        )
    if action == "replace":
        value = rule.get("value", "")
        result_kind, number, _ = classify(value)
        if kind == KIND_MISSING:
            if value is None or (isinstance(value, str) and not str(value).strip()):
                raise ValueError(
                    "replace policy needs an explicit non-empty 'value'"
                )
            return number if result_kind == KIND_FINITE else value
        if result_kind != KIND_FINITE:
            raise ValueError(
                f"replacement for {kind} values must itself be a finite "
                f"number, got {value!r}"
            )
        return number
    return None


def describe_kind(kind):
    return {
        KIND_MISSING: "\u7f3a\u5931",
        KIND_INVALID: "\u975e\u6cd5\u6587\u5b57",
        KIND_NONFINITE: "\u8d85\u51fa\u6709\u9650\u8303\u56f4",
    }.get(kind, kind)
