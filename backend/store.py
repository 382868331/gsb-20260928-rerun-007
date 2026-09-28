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
