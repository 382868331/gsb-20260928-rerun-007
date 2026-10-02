"""Analyse who is affected by a spec and attribute version differences.

Three independent causes can change cleaning output, and the API keeps
them separate:

* ``data_added``   - rows introduced by a newly appended batch;
* ``rule_changed``  - same raw data, but the configured policy changed;
* ``manual_decision`` - a per-record manual exception decided the cell.
"""
from . import pipeline


def run_with_breakdown(project_dir, spec, source_version=None, context=None):
    """Run a spec and tag every affected row as old/new vs source data.

    Returns ``(reports, rows, lineage, new_ids, total_rows)`` where each
    affected-row detail gains ``is_new`` when the row belongs to a batch
    newer than the data the source version was built on.
    """
    from . import store
    manifest = store.load_manifest(project_dir)
    if source_version is None:
        source = store.load_working(project_dir)
        source_rows = source["rows"]
        base_generation = 0  # everything is "new" only when a batch > 0
    else:
        source = store.load_version(project_dir, int(source_version))
        source_rows = source["rows"]
        base_generation = source.get("data_generation", 0)
    rows, lineage, reports = pipeline.run(
        source_rows, spec, base_lineage=source.get("lineage"),
        context=context)

    new_ids = set()
    for raw in source_rows:
        if int(raw.get("_batch") or 1) > base_generation:
            for origin in source.get("lineage", {}).get(raw["_id"],
                                                        [raw["_id"]]):
                new_ids.add(origin)

    for report in reports:
        for action in report.get("actions", []):
            origins = set(action.get("origins", []))
            action["detail"]["is_new"] = bool(origins & new_ids)
    return reports, rows, lineage, new_ids, source_rows


def rule_impact(previous_spec, next_spec, old_rows, new_rows,
                next_reports):
    """List old/new records affected when rules change under one dataset.

    The caller runs both specs over the *same* accumulated dataset.
    Rows appearing only in the newer dataset are classified as
    ``new_records``; rows already present whose outcome differs between
    the two specs are ``changed_old_records``; other affected new rows
    are ``affected_new_records``.
    """
    from . import store as _store  # noqa: F401 (symmetry for callers)
    old_ids = {r["_id"] for r in old_rows}

    changed_old = []
    affected_new = []
    for report in next_reports:
        for action in report.get("actions", []):
            origins = action.get("origins", [])
            detail = action.get("detail", {})
            entry = {
                "step": report["label"],
                "row_ids": origins,
                "description": action.get("description"),
                "action": detail.get("action"),
                "manual": bool(detail.get("manual")),
                "decision_scope": detail.get("decision_scope"),
                "source": detail.get("source"),
            }
            if any(origin in old_ids for origin in origins):
                changed_old.append(entry)
            else:
                affected_new.append(entry)

    new_records = [r for r in new_rows if r["_id"] not in old_ids]
    return {
        "new_record_count": len(new_records),
        "new_records": [r["_id"] for r in new_records],
        "changed_old_records": changed_old,
        "affected_new_records": affected_new,
    }


def _origin_outcomes(version):
    """Map every v0 origin -> outcome and how it was decided.

    Outcome is ``{"state": "present"|"dropped", "values": {...},
    "manual": bool, "rule_action": str}``. Presence is derived from
    final lineage; drop/flag/replace decisions come from step actions.
    """
    surviving = {}
    for row in version.get("rows", []):
        for origin in version.get("lineage", {}).get(row["_id"],
                                                      [row["_id"]]):
            surviving[origin] = row
    outcomes = {}
    for origin in {o for ids in version.get("lineage", {}).values()
                   for o in ids}:
        outcomes[origin] = {
            "state": "present" if origin in surviving else "dropped",
            "manual": False, "actions": [],
            "row": surviving.get(origin),
        }
    for report in version.get("step_reports", []):
        for action in report.get("actions", []):
            detail = action.get("detail", {})
            for origin in action.get("origins", []):
                entry = outcomes.setdefault(origin, {
                    "state": "dropped", "manual": False,
                    "actions": [], "row": None})
                entry["actions"].append({
                    "column": detail.get("column"),
                    "issue": detail.get("issue"),
                    "action": detail.get("action"),
                    "manual": bool(detail.get("manual")),
                    "exception_id": detail.get("exception_id"),
                    "decision_scope": detail.get("decision_scope"),
                })
                if detail.get("manual"):
                    entry["manual"] = True
    return outcomes


def _manual_for_origin(version, origin):
    """Exception ids that actually decided an origin in this version."""
    ids = set()
    for report in version.get("step_reports", []):
        for action in report.get("actions", []):
            if origin not in action.get("origins", []):
                continue
            exception_id = action.get("detail", {}).get("exception_id")
            if exception_id:
                ids.add(exception_id)
    return ids


def _specs(manifest, version_meta):
    return [s for v in manifest["versions"]
            if v["version"] == version_meta.get("version")
            for s in v.get("steps", [])]


def compare_versions(project_dir, version_a, version_b):
    """Attribute each outcome difference between two published versions.

    Each differing origin set is bucketed into exactly one cause:
    data addition, rule change, or manual decision (manual wins when
    more than one applies, because a human explicitly overrode).
    """
    from . import store
    va = store.load_version(project_dir, int(version_a))
    vb = store.load_version(project_dir, int(version_b))
    manifest = store.load_manifest(project_dir)
    meta_a = next(v for v in manifest["versions"]
                  if v["version"] == int(version_a))
    meta_b = next(v for v in manifest["versions"]
                  if v["version"] == int(version_b))
    gen_a = va.get("data_generation", 1)
    gen_b = vb.get("data_generation", 1)
    spec_a = json_steps(meta_a)
    spec_b = json_steps(meta_b)
    rules_changed = spec_a != spec_b
    manual_a = va.get("manual_exception_ids", [])
    manual_b = vb.get("manual_exception_ids", [])
    manual_changed = set(manual_a) != set(manual_b)

    attributed = {"data_added": [], "rule_changed": [],
                  "manual_decision": []}
    outcomes_a = _origin_outcomes(va)
    outcomes_b = _origin_outcomes(vb)
    # Every v0 record seen by either version counts as an origin,
    # including rows that were dropped (they still appear in the step
    # actions); lineage alone only retains surviving rows.
    origins_a = set(outcomes_a)
    origins_b = set(outcomes_b)
    data_removed = sorted(origins_a - origins_b)

    # Data additions are identified by batch generation rather than
    # lineage membership: an appended row the rules drop would otherwise
    # vanish from the newer lineage and look like an unchanged record.
    batch_origins = {}
    for batch in manifest.get("batches", []):
        for row_id in batch.get("row_ids", []):
            batch_origins[row_id] = int(batch.get("generation", 1))
    added_between = sorted(
        o for o in origins_b | origins_a
        if gen_a < batch_origins.get(o, 1) <= gen_b)
    data_added = sorted((origins_b - origins_a) | set(added_between))
    for origin in added_between:
        after = outcomes_b.get(origin, {"state": "dropped"})
        attributed["data_added"].append({
            "origins": [origin], "column": None,
            "before": None, "after": after.get("state"),
            "cause": "data_added"})
    for origin in data_added:
        if origin not in added_between:
            attributed["data_added"].append({
                "origins": [origin], "column": None,
                "before": None,
                "after": outcomes_b[origin]["state"],
                "cause": "data_added"})
    for origin in sorted(origins_a & origins_b):
        before, after = outcomes_a[origin], outcomes_b[origin]
        changed = (before["state"] != after["state"]
                   or _values(before) != _values(after))
        if not changed:
            continue
        change = {
            "origins": [origin],
            "column": _first_changed_column(before, after),
            "before": before["state"], "after": after["state"],
        }
        decided_by_a = _manual_for_origin(va, origin) & set(manual_a)
        decided_by_b = _manual_for_origin(vb, origin) & set(manual_b)
        if decided_by_a ^ decided_by_b or after["manual"] or before["manual"]:
            change["cause"] = "manual_decision"
            attributed["manual_decision"].append(change)
        else:
            change["cause"] = "rule_changed"
            attributed["rule_changed"].append(change)

    return {
        "versions": [int(version_a), int(version_b)],
        "data_generations": [gen_a, gen_b],
        "rules_changed": rules_changed,
        "manual_decisions_changed": manual_changed,
        "data_added_origins": data_added,
        "data_removed_origins": data_removed,
        "attributed_changes": attributed,
        "manual_exception_ids": {
            "a": manual_a, "b": manual_b},
    }


def json_steps(meta):
    return [{"type": s["type"], "params": s.get("params", {})}
            for s in meta.get("steps", [])]


def _values(outcome):
    row = outcome.get("row")
    if not row:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _first_changed_column(before, after):
    values_a, values_b = _values(before) or {}, _values(after) or {}
    for key in sorted(set(values_a) | set(values_b)):
        if values_a.get(key) != values_b.get(key):
            return key
    actions = [a["column"] for a in after.get("actions", [])
               if a.get("column")]
    return actions[0] if actions else None
