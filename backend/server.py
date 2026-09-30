"""Stdlib-only JSON API for the cleaning workbench.

Run:  python3 -m backend.server --port 8000
Data lives in <root>/projects (default: ./data/projects).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import pipeline, store


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
            if key not in ("_id",) and not key.startswith("_") and key not in seen:
                seen.append(key)
    return seen


def _public_rows(rows):
    """Strip internal bookkeeping but surface anomaly markers separately."""
    public = []
    anomalies = {}
    for row in rows:
        clean = {k: v for k, v in row.items() if not k.startswith("_") or k == "_id"}
        public.append(clean)
        marker = row.get("_anomalies")
        if marker:
            anomalies[row["_id"]] = marker
    return public, anomalies


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
                        public, anomalies = _public_rows(version["rows"])
                        return self._send(200, {
                            "version": version_no,
                            "rows": public,
                            "anomalies": anomalies,
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
                if parts[3] == "preview":
                    spec = {"steps": body.get("steps", [])}
                    base_no = body.get("base_version", manifest["latest_version"])
                    base = store.load_version(project_dir, base_no)
                    rows, lineage, reports = pipeline.run(base["rows"], spec)
                    public, anomalies = _public_rows(rows)
                    return self._send(200, {
                        "reports": reports,
                        "base_version": base_no,
                        "row_count_before": len(base["rows"]),
                        "row_count_after": len(rows),
                        "sample": public,
                        "anomalies": anomalies,
                    })
                if parts[3] == "apply":
                    spec = {"steps": body.get("steps", [])}
                    new_no, reports = pipeline.apply_spec(
                        project_dir, spec, label=body.get("label", ""),
                        base_version=body.get("base_version"))
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
