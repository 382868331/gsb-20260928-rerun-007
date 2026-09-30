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


def _resolve_origins(row_ids, lineage):
    """Map step-level row ids back to original (v0) row ids."""
    origins = []
    seen = set()
    for row_id in row_ids:
        for origin in lineage.get(row_id, [row_id]):
            if origin not in seen:
                seen.add(origin)
                origins.append(origin)
    return origins


def _action_records(step_type, stats, lineage):
    """Turn a step's affected_rows detail into origin-keyed action records."""
    records = []
    for item in stats.get("affected_rows", []):
        if step_type == "dedup_merge":
            origins = _resolve_origins(item.get("source_row_ids", []), lineage)
            conflicts = ", ".join(item.get("conflict_columns") or []) or "无"
            description = (
                f"重复合并：主键 {item.get('keys')}，吸收 "
                f"{', '.join(item.get('source_row_ids', []))}；冲突列：{conflicts}"
            )
        elif item.get("action") == "drop_row":
            origins = _resolve_origins([item["row_id"]], lineage)
            description = f"缺失处理：删除该行（缺失列：{', '.join(item.get('columns', []))}）"
        else:
            origins = _resolve_origins([item["row_id"]], lineage)
            label = {
                "fill_constant": "固定值填充",
                "fill_mean": "均值填充",
                "fill_median": "中位数填充",
                "fill_mode": "众数填充",
            }.get(item.get("action"), "填充")
            if step_type == "unit_convert":
                label = "单位换算"
            column = item.get("column", "")
            description = (
                f"{label}：{column} {item.get('before')} "
                f"{item.get('unit', '')} → {item.get('after')}".rstrip()
            )
        records.append({
            "origins": origins,
            "description": description,
            "detail": item,
        })
    return records


def run(rows, spec):
    """Run a spec over rows purely, without persisting anything.

    Returns (final_rows, global_lineage, step_reports).
    Raises ValueError on any invalid spec or failed step; the caller's
    data is untouched because steps copy rows and nothing is committed.
    """
    validate_spec(spec)
    current = [dict(r) for r in rows]
    global_lineage = {r["_id"]: [r["_id"]] for r in current}
    reports = []

    for step in spec["steps"]:
        step_type = step["type"]
        next_rows, local_lineage, stats = STEPS[step_type](
            current, step.get("params", {})
        )
        global_lineage = _compose(global_lineage, local_lineage)
        actions = _action_records(step_type, stats, global_lineage)
        reports.append({
            "type": step_type,
            "label": STEP_LABELS.get(step_type, step_type),
            "params": step.get("params", {}),
            "stats": stats,
            "row_count_before": len(current),
            "row_count_after": len(next_rows),
            "actions": actions,
        })
        current = next_rows

    return current, global_lineage, reports


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

    final_rows, lineage, reports = run(latest["rows"], spec)

    new_no = latest_no + 1
    version_payload = {
        "version": new_no,
        "created_from": latest_no,
        "rows": final_rows,
        "lineage": lineage,
        "step_reports": reports,
        "step_actions": [
            {"type": report["type"], "label": report["label"],
             "actions": report.get("actions", [])}
            for report in reports
        ],
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
