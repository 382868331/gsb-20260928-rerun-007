"""Stdlib-only JSON API for the cleaning workbench.

Run:  python3 -m backend.server --port 8000
Data lives in <root>/projects (default: ./data/projects).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import pipeline, store


EXAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "examples",
)


def _treatments(version, row_id):
    """List every processing step a result row went through.

    Walks the per-step lineage backwards from the final row id; the
    step's effect (converted / filled / dropped / merged / kept) is
    attached with the original r000x ids it applies to.
    """
    reports = version.get("step_reports", [])
    stage_lineages = version.get("stage_lineages")
    global_lineage = version.get("lineage", {})
    target_origins = set(global_lineage.get(row_id, [row_id]))
    treatments = []
    current_ids = {row_id}
    for index, report in enumerate(reports, 1):
        effects = {e["row_id"]: e for e in report.get("stats", {}).get("effects", [])}
        local = stage_lineages[index - 1] if stage_lineages else None
        if local is None:
            hit_ids = current_ids & set(effects)
        else:
            hit_ids = {out_id for out_id in current_ids if out_id in local}
        next_ids = set()
        for hid in sorted(hit_ids):
            effect = effects.get(hid)
            action = effect["action"] if effect else "kept"
            detail = effect["detail"] if effect else {}
            origins = set()
            if local is not None:
                for src_id in local.get(hid, [hid]):
                    origins.update(global_lineage.get(src_id, [src_id]))
            else:
                origins = set(global_lineage.get(hid, [hid]))
            origins &= target_origins
            treatments.append({
                "step": index,
                "type": report["type"],
                "label": report["label"],
                "action": action,
                "detail": detail,
                "origins": sorted(origins),
            })
            if action != "dropped":
                next_ids.add(hid)
        current_ids = next_ids
        if not current_ids:
            break
    return treatments


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
            if key != "_id" and key not in seen:
                seen.append(key)
    return seen


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
            if parts[:2] == ["api", "samples"]:
                samples = {
                    "bad": "mixed_units_duplicates.csv",
                    "clean": "mixed_units_duplicates_clean.csv",
                }
                if len(parts) == 2:
                    return self._send(200, {"samples": sorted(samples)})
                filename = samples.get(parts[2])
                if not filename:
                    return self._send(404, {"error": "unknown sample"})
                with open(os.path.join(EXAMPLES_DIR, filename),
                          encoding="utf-8") as fh:
                    return self._send(200, {"name": parts[2], "csv": fh.read()})
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
                        return self._send(200, {
                            "row_id": row_id,
                            "origins": origins,
                            "origin_rows": [raw[o] for o in origins if o in raw],
                            "clean_row": next((r for r in version["rows"]
                                               if r["_id"] == row_id), None),
                            "treatments": _treatments(version, row_id),
                        })
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
            if parts[:2] == ["api", "projects"] and len(parts) == 4:
                name = parts[2]
                project_dir = store.project_path(PROJECTS_ROOT, name)
                manifest = store.load_manifest(project_dir)
                latest = store.load_version(project_dir, manifest["latest_version"])
                spec = {"steps": body.get("steps", [])}
                if parts[3] == "preview":
                    rows, lineage, reports, _, stage_rows = pipeline.run(
                        latest["rows"], spec)
                    return self._send(200, {
                        "reports": reports,
                        "row_count_before": len(latest["rows"]),
                        "row_count_after": len(rows),
                        "sample": rows[:50],
                        "stages": [
                            {"rows": sr[:200], "row_count": len(sr),
                             "truncated": len(sr) > 200}
                            for sr in stage_rows
                        ],
                    })
                if parts[3] == "apply":
                    new_no, reports = pipeline.apply_spec(
                        project_dir, spec, label=body.get("label", ""))
                    return self._send(201, {
                        "version": new_no,
                        "reports": reports,
                    })
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
