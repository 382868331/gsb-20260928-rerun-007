"""Stdlib-only JSON API for the cleaning workbench.

Run:  python3 -m backend.server --port 8000
Data lives in <root>/projects (default: ./data/projects).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import compare, pipeline, store
from .decisions import exception_conflicts
from . import exceptions as manual_exc


PROJECTS_ROOT = os.environ.get(
    "CLEANBENCH_DATA",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "data", "projects"),
)

FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "dist",
)


def _columns(rows):
    seen = []
    for row in rows:
        for key in row:
            if not key.startswith("_") and key not in seen:
                seen.append(key)
    return seen


def _run_preview(project_dir, body):
    """Run a preview over the accumulated working dataset by default.

    Returns (reports, rows, new_ids, working_rows). Affected-row details
    are annotated with ``is_new`` so callers can list old vs new records
    separately; the exact same spec + manual decisions feed publish.
    """
    spec = {"steps": body.get("steps", [])}
    source_version = body.get("source_version")
    manual = [d for d in manual_exc.load_exceptions(project_dir)
              .get("decisions", []) if d.get("status") == "active"]
    if source_version is not None:
        source = store.load_version(project_dir, int(source_version))
        base_generation = source.get("data_generation", 1)
    else:
        manifest = store.load_manifest(project_dir)
        source = store.load_working(project_dir)
        latest = store.load_version(project_dir, manifest["latest_version"])
        base_generation = latest.get("data_generation", 1)
    rows, _lineage, reports = pipeline.run(
        source["rows"], spec, base_lineage=source.get("lineage"),
        context={"manual_decisions": manual})
    new_ids = set()
    for raw in source["rows"]:
        if int(raw.get("_batch") or 1) > base_generation:
            for origin in source.get("lineage", {}).get(raw["_id"],
                                                        [raw["_id"]]):
                new_ids.add(origin)
    rule_fingerprints = {}
    for report in reports:
        stats = report.get("stats", {})
        rule_fingerprints.update(stats.get("rule_fingerprints", {}))
        for action in report.get("actions", []):
            detail = action["detail"]
            origins = set(action.get("origins", []))
            detail["is_new"] = bool(origins & new_ids)
    stored = manual_exc.load_exceptions(project_dir)
    conflict_list = exception_conflicts(
        stored.get("decisions", []), rule_fingerprints)
    return reports, rows, new_ids, source["rows"], conflict_list


class Handler(BaseHTTPRequestHandler):
    server_version = "CleanBench/0.1"

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _error(self, exc):
        self._send(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET_static(self):
        if self.path.startswith("/api"):
            return False
        rel = self.path.split("?")[0].lstrip("/")
        if not rel:
            rel = "index.html"
        target = os.path.normpath(os.path.join(FRONTEND_DIST, rel))
        if not target.startswith(FRONTEND_DIST) or not os.path.isfile(target):
            target = os.path.join(FRONTEND_DIST, "index.html")
        if not os.path.isfile(target):
            self.send_error(404)
            return True
        suffix = os.path.splitext(target)[1]
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript",
            ".css": "text/css",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        if self.do_GET_static():
            return
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            if parts == ["api", "projects"]:
                return self._send(200, {"projects": store.list_projects(PROJECTS_ROOT)})
            if parts[:2] == ["api", "projects"] and len(parts) >= 3:
                name = parts[2]
                project_dir = store.project_path(PROJECTS_ROOT, name)
                if len(parts) == 3:
                    manifest = store.load_manifest(project_dir)
                    latest = store.load_version(project_dir, manifest["latest_version"])
                    return self._send(200, {
                        "manifest": manifest,
                        "columns": _columns(latest["rows"]),
                        "row_count": len(latest["rows"]),
                    })
                if parts[3] == "versions" and len(parts) >= 5:
                    version_no = int(parts[4])
                    version = store.load_version(project_dir, version_no)
                    if len(parts) == 5:
                        return self._send(200, {
                            "version": version_no,
                            "rows": version["rows"],
                            "columns": _columns(version["rows"]),
                            "step_reports": version["step_reports"],
                        })
                    if len(parts) == 7 and parts[5] == "lineage":
                        row_id = parts[6]
                        origins = version["lineage"].get(row_id)
                        if origins is None:
                            raise ValueError(f"row '{row_id}' not in v{version_no}")
                        v0 = store.load_version(project_dir, 0)
                        raw = {r["_id"]: r for r in v0["rows"]}
                        timeline = []
                        for step_info in version.get("step_actions", []):
                            for action in step_info.get("actions", []):
                                if row_id in action.get("origins", []):
                                    timeline.append({
                                        "step": step_info["label"],
                                        "description": action["description"],
                                    })
                        return self._send(200, {
                            "row_id": row_id,
                            "origins": origins,
                            "origin_rows": [raw[o] for o in origins if o in raw],
                            "timeline": timeline,
                        })
                if (len(parts) == 6 and parts[3] == "versions"
                        and parts[5] == "exceptions"):
                    payload = manual_exc.load_exceptions(project_dir)
                    return self._send(200, payload)
            return self._send(404, {"error": "not found"})
        except (ValueError, FileNotFoundError) as exc:
            return self._error(exc)

    def do_POST(self):
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        try:
            body = self._body()
            if parts == ["api", "projects"]:
                name = body.get("name", "").strip()
                csv_text = body.get("csv", "")
                store.ingest_csv(PROJECTS_ROOT, name, csv_text,
                                 label=body.get("label", "import"))
                return self._send(201, {"ok": True, "name": name})
            if (parts[:2] == ["api", "projects"]
                    and parts[2] and 4 <= len(parts) <= 7):
                name = parts[2]
                project_dir = store.project_path(PROJECTS_ROOT, name)
                manifest = store.load_manifest(project_dir)
                latest = store.load_version(project_dir, manifest["latest_version"])
                if parts[3] == "preview":
                    reports, rows, new_ids, working_rows, conflicts = \
                        _run_preview(project_dir, body)
                    new_rows = [r for r in working_rows
                                if r["_id"] in new_ids]
                    old_rows = [r for r in working_rows
                                if r["_id"] not in new_ids]
                    return self._send(200, {
                        "reports": reports,
                        "row_count_before": len(working_rows),
                        "row_count_after": len(rows),
                        "sample": rows,
                        "old_record_count": len(old_rows),
                        "new_record_count": len(new_rows),
                        "new_row_ids": sorted(new_ids),
                        "conflicts": conflicts,
                    })
                if parts[3] == "apply":
                    # Re-run the preview path so publication uses the exact
                    # decisions the user reviewed; block on unresolved
                    # conflicts between manual exceptions and new rules.
                    reports, rows, new_ids, working_rows, conflicts = \
                        _run_preview(project_dir, body)
                    resolutions = body.get("conflict_resolutions") or {}
                    unresolved = [c["id"] for c in conflicts
                                  if c["id"] not in resolutions]
                    if unresolved and not body.get("allow_conflicts"):
                        return self._send(409, {
                            "error": "manual exceptions conflict with the "
                                     "current rules; user must keep or "
                                     "withdraw each one",
                            "conflicts": conflicts,
                            "unresolved": unresolved})
                    if resolutions:
                        fingerprints = {}
                        for report in reports:
                            fingerprints.update(
                                report["stats"].get("rule_fingerprints", {}))
                        # Withdrawn exceptions no longer match any cell and
                        # have no current fingerprint; skip those ids.
                        active_ids = {d.get("id") for d in manual_exc
                                      .load_exceptions(project_dir)
                                      .get("decisions", [])
                                      if d.get("status") == "active"}
                        fingerprints = {key: value
                                        for key, value in fingerprints.items()
                                        if key in active_ids}
                        manual_exc.resolve_conflicts(
                            project_dir, resolutions, fingerprints)
                    spec = {"steps": body.get("steps", [])}
                    source_version = body.get("source_version")
                    manual = [d for d in manual_exc.load_exceptions(project_dir)
                              .get("decisions", [])
                              if d.get("status") == "active"]
                    new_no, reports = pipeline.apply_spec(
                        project_dir, spec, label=body.get("label", ""),
                        source_version=(int(source_version)
                                       if source_version is not None else None),
                        context={"manual_decisions": manual})
                    return self._send(201, {
                        "version": new_no,
                        "reports": reports,
                    })
                if parts[3] == "batches":
                    generation, incoming, old_rows, batch_info = \
                        store.append_batch(
                            PROJECTS_ROOT, name, body.get("csv", ""),
                            label=body.get("label", "append"))
                    return self._send(201, {
                        "generation": generation,
                        "batch": batch_info,
                        "new_rows": incoming,
                        "old_record_count": len(old_rows),
                    })
                if parts[3] == "exceptions" and len(parts) == 4:
                    # Preview first (dry_run) -> capture rule fingerprint
                    # for the targeted cell; then persist unless dry_run.
                    reports, _rows, _new, working, conflicts = \
                        _run_preview(project_dir, {
                            "steps": body.get("steps", [])})
                    key = (f"{body['row_id']}|{body['column']}|"
                           f"{body.get('stage', 'check')}|{body['issue']}")
                    fingerprint = None
                    for report in reports:
                        fingerprint = report["stats"].get(
                            "current_rule_fingerprints", {}).get(key)
                        if fingerprint:
                            break
                    if fingerprint is None:
                        raise ValueError(
                            f"record {body['row_id']} column "
                            f"{body['column']} has no current "
                            f"{body['issue']} issue; nothing to override")
                    if body.get("dry_run"):
                        return self._send(200, {
                            "ok": True, "rule_fingerprint": fingerprint})
                    record = manual_exc.add_exception(
                        project_dir, body, fingerprint)
                    return self._send(201, {"exception": record})
                if (len(parts) == 6 and parts[3] == "exceptions"
                        and parts[5] == "withdraw"):
                    record = manual_exc.withdraw_exception(
                        project_dir, parts[4])
                    return self._send(200, {"exception": record})
                if parts[3] == "compare" and len(parts) == 6:
                    result = compare.compare_versions(
                        project_dir, parts[4], parts[5])
                    return self._send(200, result)
            return self._send(404, {"error": "not found"})
        except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
            return self._error(exc)


def main():
    global PROJECTS_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default=PROJECTS_ROOT)
    args = parser.parse_args()
    PROJECTS_ROOT = args.data
    os.makedirs(PROJECTS_ROOT, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"CleanBench API on http://127.0.0.1:{args.port}  data={PROJECTS_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
