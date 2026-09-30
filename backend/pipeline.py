"""Versioned, lineage-aware cleaning pipeline.

Design:
* Source rows get stable identities r0001.. once when data is ingested.
  Original data is immutable forever.
* Every execution ("apply") of a pipeline spec creates a *new version*:
  v0 is the raw snapshot, v1+ are cleaning results. Old versions stay
  readable.
* Each step returns a local lineage map; composing the maps through the
  whole pipeline lets any result row trace back to every original row it
  was derived from (including rows merged into it).
* Execution is all-in-memory until every step succeeds; only then is the
  new version atomically written and committed to the manifest.
"""
import json
import os
import tempfile

from .steps import STEPS, STEP_LABELS


def validate_spec(spec):
    """Validate the pipeline spec; raise ValueError with a readable message."""
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("pipeline must contain at least one step")
    for index, step in enumerate(steps, 1):
        name = step.get("type")
        if name not in STEPS:
            known = ", ".join(sorted(STEPS))
            raise ValueError(f"step {index}: unknown type '{name}' (known: {known})")
        params = step.get("params")
        if not isinstance(params, dict):
            raise ValueError(f"step {index} ({name}): params must be an object")
        if name == "dedup_merge" and not params.get("keys"):
            raise ValueError(f"step {index}: dedup_merge needs non-empty 'keys'")
        if name == "unit_convert":
            if not params.get("column"):
                raise ValueError(f"step {index}: unit_convert needs 'column'")
            if not params.get("canonical_unit"):
                raise ValueError(f"step {index}: unit_convert needs 'canonical_unit'")
    return True


def _compose(global_lineage, local_lineage):
    """Map local (step-level) lineage back onto the original row ids."""
    composed = {}
    for new_id, parents in local_lineage.items():
        origins = []
        for parent in parents:
            origins.extend(global_lineage.get(parent, [parent]))
        # de-duplicate while preserving order (merge loops can overlap)
        seen = set()
        composed[new_id] = [o for o in origins if not (o in seen or seen.add(o))]
    return composed


def run(rows, spec):
    """Run a spec over rows purely, without persisting anything.

    Returns (final_rows, global_lineage, step_reports, stage_lineages,
    stage_rows). stage_lineages[i] maps step i's output ids to the input
    ids it consumed; stage_rows[i] is the full row list after step i.
    Raises ValueError on any invalid spec or failed step; the caller's
    data is untouched because steps copy rows and nothing is committed.
    """
    validate_spec(spec)
    current = [dict(r) for r in rows]
    global_lineage = {r["_id"]: [r["_id"]] for r in current}
    reports = []
    stage_lineages = []
    stage_rows = []

    for step in spec["steps"]:
        step_type = step["type"]
        next_rows, local_lineage, stats = STEPS[step_type](
            current, step.get("params", {})
        )
        global_lineage = _compose(global_lineage, local_lineage)
        stage_lineages.append(local_lineage)
        stage_rows.append(next_rows)
        reports.append({
            "type": step_type,
            "label": STEP_LABELS.get(step_type, step_type),
            "params": step.get("params", {}),
            "stats": stats,
            "row_count_before": len(current),
            "row_count_after": len(next_rows),
        })
        current = next_rows

    return current, global_lineage, reports, stage_lineages, stage_rows


def atomic_write_json(path, payload):
    """Write JSON next to path, fsync, then atomically rename into place."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def apply_spec(project_dir, spec, label=""):
    """Execute spec against the project's latest version and commit a new one.

    The new version is fully built in memory first; only when all steps
    succeed are the version file and the manifest swapped atomically.
    """
    manifest = json.load(open(os.path.join(project_dir, "manifest.json"),
                              encoding="utf-8"))
    latest_no = manifest["latest_version"]
    latest_path = os.path.join(project_dir, "versions", f"v{latest_no}.json")
    latest = json.load(open(latest_path, encoding="utf-8"))

    final_rows, lineage, reports, stage_lineages, _ = run(latest["rows"], spec)

    new_no = latest_no + 1
    version_payload = {
        "version": new_no,
        "created_from": latest_no,
        "rows": final_rows,
        "lineage": lineage,
        "stage_lineages": stage_lineages,
        "step_reports": reports,
    }
    versions_dir = os.path.join(project_dir, "versions")
    new_path = os.path.join(versions_dir, f"v{new_no}.json")
    atomic_write_json(new_path, version_payload)

    # Commit the manifest last; a crash between the two leaves an
    # unreferenced file, never a half-visible version.
    manifest["versions"].append({
        "version": new_no,
        "created_from": latest_no,
        "label": label,
        "steps": [{"type": s["type"], "params": s.get("params", {})}
                  for s in spec["steps"]],
        "reports": reports,
    })
    manifest["latest_version"] = new_no
    atomic_write_json(os.path.join(project_dir, "manifest.json"), manifest)
    return new_no, reports
