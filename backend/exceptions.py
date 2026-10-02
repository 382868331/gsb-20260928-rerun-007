"""Project-level manual exception decisions.

Exceptions are keyed by stable original row id (r0001..) plus a scope
that identifies the rule they override:

    scope = "{step_type}:{column}:{issue}"

They live in ``exceptions.json`` next to the manifest, so saving and
reopening the project - or revoking a decision - restores the exact
original value, unit-conversion outcome and exclusion reason per row.
"""
import json
import os

from .pipeline import atomic_write_json

VALID_ACTIONS = ("flag", "drop", "replace")


def path_for(project_dir):
    return os.path.join(project_dir, "exceptions.json")


def load_exceptions(project_dir):
    target = path_for(project_dir)
    if not os.path.isfile(target):
        return {}
    with open(target, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("exceptions", {})


def save_exceptions(project_dir, exceptions):
    atomic_write_json(path_for(project_dir), {"exceptions": exceptions})


def key_for(row_id, scope):
    return f"{row_id}|{scope}"


def set_exception(project_dir, row_id, scope, action, replacement=None,
                  reason="", batch=None, mapping_id=None):
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"manual action must be one of {', '.join(VALID_ACTIONS)}"
        )
    exceptions = load_exceptions(project_dir)
    exceptions[key_for(row_id, scope)] = {
        "row_id": row_id, "scope": scope, "action": action,
        "replacement": replacement, "reason": reason or "人工例外",
        "active": True, "batch": batch, "mapping_id": mapping_id,
        "needs_recheck": False,
    }
    save_exceptions(project_dir, exceptions)
    return exceptions


def revoke_exception(project_dir, row_id, scope):
    """Revoke one decision; the row then follows the configured rules."""
    exceptions = load_exceptions(project_dir)
    key = key_for(row_id, scope)
    if key not in exceptions:
        raise ValueError(f"no manual exception for {key}")
    exceptions[key]["active"] = False
    exceptions[key]["revoked"] = True
    save_exceptions(project_dir, exceptions)
    return exceptions


def active_map(exceptions):
    return {key: item for key, item in exceptions.items()
            if item.get("active") and not item.get("needs_recheck")}


def mark_needs_recheck(project_dir, keys):
    exceptions = load_exceptions(project_dir)
    for key in keys:
        if key in exceptions:
            exceptions[key]["needs_recheck"] = True
            exceptions[key]["active"] = False
    save_exceptions(project_dir, exceptions)
    return exceptions
