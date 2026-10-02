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
        row = {"_id": f"r{index:04d}", "_batch": 1}
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
    # The working dataset accumulates later appended batches; every
    # published version is an immutable snapshot of some generation.
    working = {"generation": 1, "rows": rows,
               "lineage": dict(v0["lineage"])}
    atomic_write_json(os.path.join(project_dir, "working.json"), working)
    manifest = {
        "name": name,
        "latest_version": 0,
        "working_generation": 1,
        "batches": [{"generation": 1, "label": label,
                     "row_ids": [r["_id"] for r in rows],
                     "row_count": len(rows)}],
        "versions": [{"version": 0, "created_from": None, "label": label,
                      "steps": [], "reports": []}],
    }
    atomic_write_json(os.path.join(project_dir, "manifest.json"), manifest)
    return project_dir


def load_working(project_dir):
    path = os.path.join(project_dir, "working.json")
    if not os.path.isfile(path):
        # Projects created before batch support: v0 is the working set.
        v0 = load_version(project_dir, 0)
        return {"generation": 1, "rows": v0["rows"],
                "lineage": v0.get("lineage", {r["_id"]: [r["_id"]]
                                              for r in v0["rows"]})}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_working(project_dir, working):
    atomic_write_json(os.path.join(project_dir, "working.json"), working)


def append_batch(projects_root, name, csv_text, label="append"):
    """Append a new experiment batch under the existing source rules.

    Already published versions are never touched: only ``working.json``
    (the accumulated raw dataset) gains a new generation, and new rows
    receive continuation ids rNNNN. Returns (generation, new_rows,
    old_rows, batch_info).
    """
    project_dir = project_path(projects_root, name)
    if not os.path.exists(project_dir):
        raise ValueError(f"project '{name}' not found")
    manifest = load_manifest(project_dir)
    working = load_working(project_dir)
    old_rows = [dict(r) for r in working["rows"]]

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    incoming_fields = [f.strip() for f in reader.fieldnames if f is not None]
    existing_fields = [k for k in old_rows[0].keys() if not k.startswith("_")] \
        if old_rows else incoming_fields
    if set(incoming_fields) != set(existing_fields):
        added = sorted(set(incoming_fields) - set(existing_fields))
        missing = sorted(set(existing_fields) - set(incoming_fields))
        raise ValueError(
            f"batch columns must match the existing dataset "
            f"(new-only: {added or 'none'}, missing: {missing or 'none'})")

    start_index = max(
        (int(r["_id"][1:]) for r in working["rows"]
         if r.get("_id", "r").startswith("r") and r["_id"][1:].isdigit()),
        default=0)
    next_generation = working["generation"] + 1
    new_rows = []
    for offset, record in enumerate(reader, 1):
        row = {"_id": f"r{start_index + offset:04d}",
               "_batch": next_generation}
        for key, value in record.items():
            if key is None:
                continue
            row[key.strip()] = value
        new_rows.append(row)
    if not new_rows:
        raise ValueError("CSV contains no data rows")

    working["generation"] = next_generation
    working["rows"] = old_rows + new_rows
    working["lineage"].update({r["_id"]: [r["_id"]] for r in new_rows})
    save_working(project_dir, working)

    batch_info = {"generation": next_generation, "label": label,
                  "row_ids": [r["_id"] for r in new_rows],
                  "row_count": len(new_rows)}
    manifest.setdefault("batches", []).append(batch_info)
    manifest["working_generation"] = next_generation
    atomic_write_json(os.path.join(project_dir, "manifest.json"), manifest)
    return next_generation, new_rows, old_rows, batch_info
