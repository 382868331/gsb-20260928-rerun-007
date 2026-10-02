"""Project storage: open existing projects, ingest new CSV data.

Layout on disk (all JSON, human-inspectable):
  project_dir/
    manifest.json       # versions, latest_version, step history
    versions/v0.json    # raw snapshot, immutable
    versions/v1.json    # first cleaning result, immutable
    ...
"""
import csv
import io
import json
import os

from . import schema_mapping
from .pipeline import atomic_write_json


def project_path(projects_root, name):
    safe = "".join(c for c in name if c.isalnum() or c in "-_.").strip(".")
    if not safe:
        raise ValueError("invalid project name")
    return os.path.join(projects_root, safe)


def list_projects(projects_root):
    if not os.path.isdir(projects_root):
        return []
    names = []
    for entry in sorted(os.listdir(projects_root)):
        if os.path.isfile(os.path.join(projects_root, entry, "manifest.json")):
            names.append(entry)
    return names


def load_manifest(project_dir):
    with open(os.path.join(project_dir, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)


def load_version(project_dir, version_no):
    path = os.path.join(project_dir, "versions", f"v{version_no}.json")
    if not os.path.isfile(path):
        raise ValueError(f"version v{version_no} not found")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ingest_csv(projects_root, name, csv_text, label="import"):
    """Create a new project from CSV text. Row ids r0001.. are assigned
    once here and stay stable across every later version."""
    project_dir = project_path(projects_root, name)
    if os.path.exists(project_dir):
        raise ValueError(f"project '{name}' already exists")

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    rows = []
    for index, record in enumerate(reader, 1):
        row = {"_id": f"r{index:04d}"}
        for key, value in record.items():
            if key is None:
                continue
            row[key.strip()] = value
        rows.append(row)
    if not rows:
        raise ValueError("CSV contains no data rows")

    os.makedirs(os.path.join(project_dir, "versions"))
    v0 = {
        "version": 0,
        "created_from": None,
        "rows": rows,
        "lineage": {r["_id"]: [r["_id"]] for r in rows},
        "step_reports": [],
    }
    atomic_write_json(os.path.join(project_dir, "versions", "v0.json"), v0)
    manifest = {
        "name": name,
        "latest_version": 0,
        "versions": [{"version": 0, "created_from": None, "label": label,
                      "steps": [], "reports": []}],
    }
    atomic_write_json(os.path.join(project_dir, "manifest.json"), manifest)
    return project_dir


def append_batch(projects_root, name, csv_text, batch_label=""):
    """Append a new experiment batch to an existing project.

    Published versions never change: the raw additions are recorded in
    an append-only ``batches/batch-N.json`` file and in
    ``workspace.json``; v0 and every published version file stay exactly
    as they were.
    """
    project_dir = project_path(projects_root, name)
    if not os.path.exists(project_dir):
        raise ValueError(f"project '{name}' not found")
    new_columns, records = schema_mapping.parse_csv(csv_text)

    v0 = load_version(project_dir, 0)
    old_columns = []
    for row in v0["rows"]:
        for key in row:
            if not key.startswith("_") and key not in old_columns:
                old_columns.append(key)
    unknown = [c for c in new_columns if c not in old_columns]
    if unknown:
        return _append_structured_batch(
            project_dir, v0, old_columns, new_columns, records,
            batch_label=batch_label)

    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            workspace = json.load(handle)
        base_rows = workspace["rows"]
        appended = workspace.get("appended", [])
    else:
        base_rows = v0["rows"]
        appended = []
    existing_ids = {row["_id"] for row in base_rows}
    next_index = max((int(rid[1:]) for rid in existing_ids
                      if rid.startswith("r") and rid[1:].isdigit()),
                     default=0)
    new_rows = []
    for record in records:
        next_index += 1
        row = {"_id": f"r{next_index:04d}"}
        for key in old_columns:
            value = record.get(key, "")
            row[key] = "" if value is None else value
        new_rows.append(row)
    if not new_rows:
        raise ValueError("CSV contains no data rows")

    batches_dir = os.path.join(project_dir, "batches")
    os.makedirs(batches_dir, exist_ok=True)
    batch_no = len(appended_batch_files(project_dir)) + 1
    atomic_write_json(os.path.join(batches_dir, f"batch-{batch_no}.json"), {
        "batch": batch_no, "label": batch_label or f"追加批次 {batch_no}",
        "rows": new_rows,
    })
    all_rows = list(base_rows) + new_rows
    atomic_write_json(workspace_path, {
        "rows": all_rows,
        "lineage": {r["_id"]: [r["_id"]] for r in all_rows},
        "appended": appended + [
            {"_id": r["_id"], "batch": batch_no,
             "label": batch_label or f"追加批次 {batch_no}"}
            for r in new_rows],
    })
    return {"project_dir": project_dir, "new_rows": new_rows,
            "new_ids": [r["_id"] for r in new_rows],
            "batch": batch_no, "schema_status": "compatible"}


def appended_batch_files(project_dir):
    batches_dir = os.path.join(project_dir, "batches")
    if not os.path.isdir(batches_dir):
        return []
    return sorted(f for f in os.listdir(batches_dir)
                  if f.startswith("batch-") and f.endswith(".json"))


def _append_structured_batch(project_dir, v0, old_columns, new_columns,
                             records, batch_label=""):
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            workspace = json.load(handle)
        existing_rows = workspace.get("raw_rows", workspace.get("rows", []))
    else:
        existing_rows = v0["rows"]
    next_index = max((int(rid[1:]) for rid in
                      {row["_id"] for row in existing_rows}
                      if rid.startswith("r") and rid[1:].isdigit()),
                     default=0)
    raw_rows = []
    for record in records:
        next_index += 1
        row = {"_id": f"r{next_index:04d}"}
        row.update(record)
        raw_rows.append(row)

    batches_dir = os.path.join(project_dir, "batches")
    os.makedirs(batches_dir, exist_ok=True)
    batch_no = len(appended_batch_files(project_dir)) + 1
    manifest = load_manifest(project_dir)
    steps = manifest["versions"][-1].get("steps", []) if manifest.get("versions") else []
    proposal = schema_mapping.build_proposal(
        old_columns, new_columns, raw_rows, steps=steps, batch=batch_no)
    payload = {
        "batch": batch_no,
        "label": batch_label or f"追加批次 {batch_no}",
        "schema_status": "changed",
        "columns": new_columns,
        "raw_rows": raw_rows,
        "proposal": proposal,
        "confirmed": [],
        "revoked_mappings": [],
    }
    atomic_write_json(os.path.join(batches_dir, f"batch-{batch_no}.json"),
                      payload)
    _rebuild_workspace(project_dir)
    return {"project_dir": project_dir, "new_rows": raw_rows,
            "new_ids": [r["_id"] for r in raw_rows],
            "batch": batch_no, "schema_status": "changed",
            "proposal": proposal}


def _batch_payloads(project_dir):
    payloads = []
    for filename in appended_batch_files(project_dir):
        with open(os.path.join(project_dir, "batches", filename),
                  encoding="utf-8") as handle:
            payloads.append(json.load(handle))
    return sorted(payloads, key=lambda item: item["batch"])


def load_batch(project_dir, batch_no):
    path = os.path.join(project_dir, "batches", f"batch-{batch_no}.json")
    if not os.path.isfile(path):
        raise ValueError(f"batch {batch_no} not found")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save_batch(project_dir, payload):
    atomic_write_json(
        os.path.join(project_dir, "batches", f"batch-{payload['batch']}.json"),
        payload)
    _rebuild_workspace(project_dir)


def batch_projection(payload):
    confirmed = schema_mapping.effective_mappings(
        payload.get("proposal", {}), payload.get("confirmed", []))
    measurements = payload.get("proposal", {}).get("measurements", [])
    confirmed_ids = {m["id"] for m in confirmed}
    inherited_ids = {m["id"] for m in confirmed if m.get("status") == "inherited"}
    return {
        "batch": payload["batch"],
        "label": payload.get("label"),
        "schema_status": payload.get("schema_status", "compatible"),
        "proposal": payload.get("proposal"),
        "confirmed": confirmed,
        "confirmed_ids": sorted(confirmed_ids - inherited_ids),
        "inherited_ids": sorted(inherited_ids),
        "pending_ids": [m["id"] for m in measurements
                        if m.get("status") not in ("confirmed", "inherited")
                        and m["id"] not in confirmed_ids],
    }


def confirm_mappings(project_dir, batch_no, confirmed, replace=False):
    payload = load_batch(project_dir, batch_no)
    if payload.get("schema_status") != "changed":
        raise ValueError("batch does not contain a changed schema")
    mappings = schema_mapping.confirmed_map(payload["proposal"], confirmed)
    current = [] if replace else payload.get("confirmed", [])
    by_id = {item.get("id") or item.get("mapping_id"): item for item in current}
    for mapping in mappings:
        by_id[mapping["id"]] = {
            "id": mapping["id"],
            "target_measurement": mapping["target_measurement"],
            "target_unit_column": mapping.get("target_unit_column"),
            "fixed_unit": mapping.get("fixed_unit"),
        }
    payload["confirmed"] = list(by_id.values())
    payload["revoked_mappings"] = [m for m in payload.get("revoked_mappings", [])
                                   if m not in by_id]
    save_batch(project_dir, payload)
    return batch_projection(payload)


def revoke_mapping(project_dir, batch_no, mapping_id):
    payload = load_batch(project_dir, batch_no)
    payload["confirmed"] = [item for item in payload.get("confirmed", [])
                             if item.get("id") != mapping_id]
    revoked = set(payload.get("revoked_mappings", []))
    revoked.add(mapping_id)
    payload["revoked_mappings"] = sorted(revoked)
    for measurement in payload.get("proposal", {}).get("measurements", []):
        if measurement["id"] == mapping_id:
            measurement["status"] = "revoked"
            measurement["target_measurement"] = None
    save_batch(project_dir, payload)
    return batch_projection(payload)


def _rebuild_workspace(project_dir):
    v0 = load_version(project_dir, 0)
    old_columns = []
    for row in v0["rows"]:
        for key in row:
            if not key.startswith("_") and key not in old_columns:
                old_columns.append(key)
    all_rows = [dict(r) for r in v0["rows"]]
    raw_rows = [dict(r) for r in v0["rows"]]
    lineage = {r["_id"]: [r["_id"]] for r in v0["rows"]}
    appended = []
    for payload in _batch_payloads(project_dir):
        batch_rows = payload.get("new_rows") or payload.get("raw_rows", [])
        raw_rows.extend(dict(r) for r in batch_rows)
        meta = {"batch": payload["batch"], "label": payload.get("label"),
                "schema_status": payload.get("schema_status", "compatible")}
        if payload.get("schema_status") == "changed":
            confirmed = schema_mapping.effective_mappings(
                payload["proposal"], payload.get("confirmed", []))
            total = len(payload["proposal"].get("measurements", []))
            pending = total - len([m for m in confirmed
                                   if m.get("status") != "inherited"])
            ruled_pending = [
                m for m in payload["proposal"].get("measurements", [])
                if m.get("rule_status") in (
                    "needs_correspondence", "needs_unit_correspondence")
                and not any(c["id"] == m["id"] and
                            c.get("status") == "confirmed"
                            for c in confirmed)]
            unresolved_targets = [
                m.get("target_measurement") or
                (m.get("candidate_measurements") or [None])[0]
                for m in ruled_pending]
            unresolved_targets = [m for m in unresolved_targets if m]
            canonical, _ = schema_mapping.materialize_rows(
                old_columns, payload["raw_rows"], confirmed,
                unresolved_targets=unresolved_targets)
            all_rows.extend(canonical)
            for row in canonical:
                lineage[row["_id"]] = [row["_id"]]
            meta["materialized_row_ids"] = [r["_id"] for r in canonical]
            meta["confirmed_count"] = len([
                m for m in confirmed if m.get("status") == "confirmed"])
            meta["pending_count"] = pending
        else:
            all_rows.extend(dict(r) for r in batch_rows)
            for row in batch_rows:
                lineage[row["_id"]] = [row["_id"]]
        appended.extend({"_id": r["_id"], **meta} for r in batch_rows)
    atomic_write_json(os.path.join(project_dir, "workspace.json"), {
        "rows": all_rows,
        "raw_rows": raw_rows,
        "lineage": lineage,
        "appended": appended,
        "schema_batches": [batch_projection(p)
                           for p in _batch_payloads(project_dir)
                           if p.get("schema_status") == "changed"],
    })


def working_rows(project_dir):
    """Return the current working rows: v0 plus every appended batch."""
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data["rows"], data["lineage"], data.get("appended", [])
    v0 = load_version(project_dir, 0)
    return v0["rows"], v0["lineage"], []


def working_rows_extended(project_dir):
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return (data["rows"], data["lineage"], data.get("appended", []),
                data.get("schema_batches", []))
    v0 = load_version(project_dir, 0)
    return v0["rows"], v0["lineage"], [], []


def changed_batches(project_dir):
    return [batch_projection(p) for p in _batch_payloads(project_dir)
            if p.get("schema_status") == "changed"]


def raw_rows(project_dir):
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("raw_rows", data.get("rows", []))
    return load_version(project_dir, 0)["rows"]
