"""Per-cell cleaning decisions: source policy + manual exceptions.

A cell with an anomaly has its effective decision resolved in exactly
one place so that preview, stats and a published version can never
disagree:

1. an active manual exception for this exact record/column/issue wins;
2. otherwise the policy configured for the row's source/batch wins;
3. otherwise the global policy for the issue kind applies.

Every decision carries a stable ``fingerprint`` describing the rule it
is based on. When a rule changes later, a previously accepted manual
exception that conflicts with the new rule is reported as a conflict
and the user must explicitly keep or withdraw it before publishing.
"""
import hashlib
import json

from .steps.numbers import POLICY_LABELS, resolve_policy


def row_source(row, source_column=None):
    """Return the source label of a row.

    A data column (e.g. ``lab``) wins when the pipeline names one;
    otherwise the ingestion batch recorded in ``_batch`` is used.
    """
    if source_column:
        value = row.get(source_column)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    batch = row.get("_batch")
    return str(batch) if batch is not None else None


def normalize_action(action):
    if action == "drop_row":
        return "drop"
    return action


def rule_fingerprint(column, issue, stage, policy):
    """Hash of the *rule* that would decide a cell (no row data).

    Manual exceptions remember the fingerprint captured when they were
    created, so a later rule edit is detectable per record.
    """
    payload = {
        "column": column,
        "issue": issue,
        "stage": stage or "check",
        "scope": "manual",
        "action": normalize_action(policy["action"]),
        "replacement": policy.get("replacement"),
        "source": policy.get("source"),
        "source_specific": bool(policy.get("source_specific")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def exception_matches(decision, row_id, column, issue, stage):
    if decision.get("status") != "active":
        return False
    if decision.get("row_id") != row_id or decision.get("column") != column:
        return False
    if issue and decision.get("issue") not in (None, "", issue):
        return False
    exc_stage = decision.get("stage")
    if exc_stage and exc_stage != stage:
        return False
    return True


def find_exception(manual_decisions, row_id, column, issue, stage):
    for decision in manual_decisions or []:
        if exception_matches(decision, row_id, column, issue, stage):
            return decision
    return None


def resolve_decision(policies, issue, row, column, stage,
                     source_column=None, manual_decisions=None):
    """Resolve the effective action for one anomalous cell.

    Returns ``(policy_like, scope, exception)`` where ``policy_like`` is
    a dict with action/replacement (usable like a normal policy),
    ``scope`` is ``manual`` / ``source:<name>`` / ``global`` and
    ``exception`` is the matched manual decision or None.
    """
    source = row_source(row, source_column)
    rule_policy = resolve_policy(policies, issue, source)
    exception = find_exception(
        manual_decisions, row["_id"], column, issue, stage)
    if exception is not None:
        policy = {
            "action": normalize_action(exception.get("action", "flag")),
            "replacement": exception.get("replacement"),
            "source": source,
            "source_specific": rule_policy.get("source_specific", False),
        }
        return policy, "manual", exception
    scope = f"source:{source}" if rule_policy.get("source_specific") else "global"
    rule_policy["action"] = normalize_action(rule_policy["action"])
    return rule_policy, scope, None


def describe_scope(scope, source):
    if scope == "manual":
        return f"人工例外（来源 {source}）" if source else "人工例外"
    if scope.startswith("source:"):
        return f"来源规则 {source}"
    return "全局规则"


def action_label(action):
    return POLICY_LABELS.get(normalize_action(action), action)


def exception_conflicts(manual_decisions, rules):
    """Return active exceptions whose underlying rule has changed.

    ``rules`` maps decision id -> current rule fingerprint. Exceptions
    created against a rule that has since changed and that have not been
    re-confirmed are returned for the user to keep or withdraw.
    """
    conflicts = []
    for decision in manual_decisions or []:
        if decision.get("status") != "active":
            continue
        decision_id = decision.get("id")
        current = rules.get(decision_id)
        if current is None:
            continue
        if decision.get("rule_fingerprint") != current:
            conflicts.append({
                "id": decision_id,
                "row_id": decision.get("row_id"),
                "column": decision.get("column"),
                "issue": decision.get("issue"),
                "manual_action": normalize_action(
                    decision.get("action", "flag")),
                "current_rule_fingerprint": current,
                "saved_rule_fingerprint": decision.get("rule_fingerprint"),
            })
    return conflicts
