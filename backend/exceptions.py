"""Manual per-record exception decisions, persisted and auditable.

Exceptions live in ``exceptions.json`` inside the project directory and
are part of the working state (not of any immutable version): a
published version records the decisions that existed at publish time in
its step reports, while this file keeps the full lifecycle for reopen,
withdraw and rule-conflict checking.
"""
import json
import os

from .pipeline import atomic_write_json
from .steps.numbers import parse_number

VALID_ACTIONS = {"flag", "drop", "replace"}


def _path(project_dir):
    return os.path.join(project_dir, "exceptions.json")


def load_exceptions(project_dir):
    path = _path(project_dir)
    if not os.path.isfile(path):
        return {"next_id": 1, "decisions": []}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_exceptions(project_dir, payload):
    atomic_write_json(_path(project_dir), payload)


def active_decisions(project_dir):
    return [d for d in load_exceptions(project_dir).get("decisions", [])
            if d.get("status") == "active"]


def add_exception(project_dir, decision, rule_fingerprint):
    """Add a manual exception. ``decision`` comes from the API user."""
    payload = load_exceptions(project_dir)
    required = ("row_id", "column", "issue", "action")
    missing = [key for key in required if not decision.get(key)]
    if missing:
        raise ValueError(f"manual exception missing fields: {missing}")
    action = decision["action"]
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"manual action must be one of {sorted(VALID_ACTIONS)}")
    replacement = decision.get("replacement")
    if action == "replace":
        parsed = parse_number(replacement)
        if parsed is None:
            raise ValueError(
                "manual replace needs a finite numeric replacement")
        replacement = parsed

    # A repeat decision for the same cell replaces the previous active one
    # but the withdrawn row is retained for audit.
    for existing in payload["decisions"]:
        if (existing.get("status") == "active"
                and existing.get("row_id") == decision["row_id"]
                and existing.get("column") == decision["column"]
                and existing.get("issue") == decision["issue"]
                and existing.get("stage") == decision.get("stage")):
            existing["status"] = "superseded"

    decision_id = f"m{payload['next_id']:04d}"
    payload["next_id"] += 1
    record = {
        "id": decision_id,
        "row_id": decision["row_id"],
        "column": decision["column"],
        "issue": decision["issue"],
        "stage": decision.get("stage"),
        "action": action,
        "replacement": replacement,
        "reason": decision.get("reason", ""),
        "status": "active",
        "rule_fingerprint": rule_fingerprint,
    }
    payload["decisions"].append(record)
    save_exceptions(project_dir, payload)
    return record


def withdraw_exception(project_dir, decision_id):
    """Withdraw one exception; the audit record is retained."""
    payload = load_exceptions(project_dir)
    for existing in payload["decisions"]:
        if existing.get("id") == decision_id:
            if existing.get("status") != "active":
                raise ValueError(
                    f"exception {decision_id} is not active "
                    f"(status: {existing.get('status')})")
            existing["status"] = "withdrawn"
            save_exceptions(project_dir, payload)
            return existing
    raise ValueError(f"exception '{decision_id}' not found")


def resolve_conflicts(project_dir, resolutions, current_fingerprints):
    """Apply user keep/withdraw choices for rule conflicts.

    ``resolutions`` maps exception id -> "keep" | "withdraw". A kept
    exception is re-bound to the new rule fingerprint so it only warns
    again on the *next* rule change.
    """
    payload = load_exceptions(project_dir)
    by_id = {d.get("id"): d for d in payload["decisions"]}
    for decision_id, choice in (resolutions or {}).items():
        decision = by_id.get(decision_id)
        if decision is None:
            raise ValueError(f"exception '{decision_id}' not found")
        if choice not in ("keep", "withdraw"):
            raise ValueError(
                f"resolution for {decision_id} must be 'keep' or 'withdraw'")
        if choice == "withdraw":
            decision["status"] = "withdrawn_conflict"
        else:
            new_fingerprint = current_fingerprints.get(decision_id)
            if new_fingerprint is None:
                raise ValueError(
                    f"no current rule fingerprint for {decision_id}")
            decision["rule_fingerprint"] = new_fingerprint
    save_exceptions(project_dir, payload)
