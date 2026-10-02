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
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    new_columns = [c.strip() for c in reader.fieldnames if c is not None]

    v0 = load_version(project_dir, 0)
    old_columns = []
    for row in v0["rows"]:
        for key in row:
            if not key.startswith("_") and key not in old_columns:
                old_columns.append(key)
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            workspace = json.load(handle)
        base_rows = workspace["rows"]
        appended = workspace.get("appended", [])
    else:
        base_rows = v0["rows"]
        appended = []
    batches_dir = os.path.join(project_dir, "batches")
    batch_no = len(appended_batch_files(project_dir)) + 1
    existing_ids = {row["_id"] for row in base_rows}
    next_index = max((int(rid[1:]) for rid in existing_ids
                      if rid.startswith("r") and rid[1:].isdigit()),
                     default=0)
    new_rows = []
    for record in reader:
        next_index += 1
        row = {"_id": f"r{next_index:04d}", "_batch": batch_no}
        for key in new_columns:
            value = record.get(key, "")
            row[key] = "" if value is None else value
        new_rows.append(row)
    if not new_rows:
        raise ValueError("CSV contains no data rows")

    os.makedirs(batches_dir, exist_ok=True)
    atomic_write_json(os.path.join(batches_dir, f"batch-{batch_no}.json"), {
        "batch": batch_no, "label": batch_label or f"追加批次 {batch_no}",
        "columns": new_columns,
        "rows": new_rows,
    })
    all_rows = list(base_rows) + new_rows
    atomic_write_json(workspace_path, {
        "rows": all_rows,
        "lineage": {r["_id"]: [r["_id"]] for r in all_rows},
        "appended": appended + [
            {"_id": r["_id"], "batch": batch_no,
             "label": batch_label or f"追加批次 {batch_no}",
             "columns": new_columns}
            for r in new_rows],
    })
    return {"project_dir": project_dir, "new_rows": new_rows,
            "new_ids": [r["_id"] for r in new_rows],
            "batch": batch_no}


def appended_batch_files(project_dir):
    batches_dir = os.path.join(project_dir, "batches")
    if not os.path.isdir(batches_dir):
        return []
    return sorted(f for f in os.listdir(batches_dir)
                  if f.startswith("batch-") and f.endswith(".json"))


def working_rows(project_dir):
    """Return the current working rows: v0 plus every appended batch."""
    workspace_path = os.path.join(project_dir, "workspace.json")
    if os.path.isfile(workspace_path):
        with open(workspace_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data["rows"], data["lineage"], data.get("appended", [])
    v0 = load_version(project_dir, 0)
    return v0["rows"], v0["lineage"], []


def mappings_path(project_dir):
    return os.path.join(project_dir, "mappings.json")


def load_mappings(project_dir):
    path = mappings_path(project_dir)
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: item for key, item in data.get("mappings", {}).items()
            if item.get("status") != "revoked"}


def save_mapping_records(project_dir, records):
    mappings = {item["id"]: item for item in records}
    atomic_write_json(mappings_path(project_dir), {"mappings": mappings})
    return mappings


def save_mapping(project_dir, mapping):
    path = mappings_path(project_dir)
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            all_records = json.load(handle).get("mappings", {})
    else:
        all_records = {}
    all_records[mapping["id"]] = mapping
    atomic_write_json(path, {"mappings": all_records})
    return load_mappings(project_dir)


def revoke_mapping(project_dir, mapping_id):
    path = mappings_path(project_dir)
    if not os.path.isfile(path):
        raise ValueError(f"mapping '{mapping_id}' not found")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    records = data.get("mappings", {})
    if mapping_id not in records:
        raise ValueError(f"mapping '{mapping_id}' not found")
    records[mapping_id]["status"] = "revoked"
    records[mapping_id]["revoked"] = True
    atomic_write_json(path, {"mappings": records})
    return {key: item for key, item in records.items()
            if item.get("status") != "revoked"}
