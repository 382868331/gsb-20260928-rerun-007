"""Stdlib-only JSON API for the cleaning workbench.

Run:  python3 -m backend.server --port 8000
Data lives in <root>/projects (default: ./data/projects).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (analysis, exceptions as exc_store, pipeline,
               schema_mapping, store)


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


def _structure_context(rows, schema_batches):
    actions = []
    confirmed_ids = set()
    pending = []
    by_batch = {item["batch"]: item for item in schema_batches}
    for row in rows:
        for provenance in row.get("_structure_provenance", []):
            text = (
                f"结构对应：{', '.join(provenance['source_columns'])} "
                f"→ {provenance['target_measurement']}；"
                f"原始文字 {provenance.get('original_text')!r}"
            )
            explanation = provenance.get("unit_explanation")
            if explanation:
                text += f"；{explanation}"
            actions.append({"origins": [row["_id"]],
                            "description": text,
                            "detail": provenance})
            confirmed_ids.add(provenance.get("mapping_id"))
    for item in schema_batches:
        for mapping_id in item.get("pending_ids", []):
            pending.append({"batch": item["batch"], "mapping_id": mapping_id})
    adopted = {
        "status": "partial" if pending else "complete",
        "confirmed_mapping_ids": sorted(confirmed_ids),
        "pending_mappings": pending,
        "batch_count": len(by_batch),
    }
    return actions, adopted


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

    def _snapshot_workspace(self, project_dir, manifest, rows, lineage,
                            structure_actions=None, adopted_scope=None):
        """Commit appended batches as a regular append version (no rules).

        The version records data addition only: no cleaning steps run,
        and previously published versions stay byte-for-byte intact.
        """
        new_no = manifest["latest_version"] + 1
        payload = {
            "version": new_no,
            "created_from": 0,
            "rows": rows, "lineage": lineage,
            "step_reports": [], "step_actions": [],
            "structure_actions": structure_actions or [],
            "adopted_scope": adopted_scope or {"status": "workspace"},
            "kind": "batch_append",
        }
        pipeline.atomic_write_json(
            os.path.join(project_dir, "versions", f"v{new_no}.json"),
            payload)
        manifest["versions"].append({
            "version": new_no, "created_from": 0,
            "label": "追加实验批次", "steps": [], "reports": [],
            "kind": "batch_append",
            "adopted_scope": adopted_scope or {"status": "workspace"},
        })
        manifest["latest_version"] = new_no
        pipeline.atomic_write_json(
            os.path.join(project_dir, "manifest.json"), manifest)
        return new_no

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
                        "exceptions": exc_store.load_exceptions(project_dir),
                        "appended": store.working_rows_extended(project_dir)[2],
                        "schema_batches": store.working_rows_extended(project_dir)[3],
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
                            "structure_actions": version.get("structure_actions", []),
                            "adopted_scope": version.get("adopted_scope"),
                        })
                    if len(parts) == 7 and parts[5] == "lineage":
                        row_id = parts[6]
                        origins = version["lineage"].get(row_id)
                        if origins is None:
                            raise ValueError(f"row '{row_id}' not in v{version_no}")
                        v0 = store.load_version(project_dir, 0)
                        raw = {r["_id"]: r
                               for r in v0["rows"] + store.raw_rows(project_dir)}
                        timeline = []
                        for action in version.get("structure_actions", []):
                            if row_id in action.get("origins", []):
                                timeline.append({
                                    "step": "结构对应",
                                    "description": action["description"],
                                })
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
            if parts[:2] == ["api", "projects"] and len(parts) >= 4:
                name = parts[2]
                project_dir = store.project_path(PROJECTS_ROOT, name)
                manifest = store.load_manifest(project_dir)
                (work_rows, work_lineage, appended,
                 schema_batches) = store.working_rows_extended(project_dir)
                if len(parts) == 5 and parts[3] == "batches":
                    result = store.append_batch(
                        PROJECTS_ROOT, name, body.get("csv", ""),
                        batch_label=body.get("label", ""))
                    return self._send(201, {
                        "ok": True, "batch": result["batch"],
                        "schema_status": result.get("schema_status", "compatible"),
                        "proposal": result.get("proposal"),
                        "new_ids": result["new_ids"],
                        "new_rows": result["new_rows"],
                    })
                if len(parts) == 6 and parts[3] == "batches" and parts[5] in (
                        "proposal", "mappings", "mapping-diff"):
                    batch_no = int(parts[4])
                    projection = store.batch_projection(
                        store.load_batch(project_dir, batch_no))
                    if parts[5] == "proposal":
                        return self._send(200, projection)
                    if parts[5] == "mapping-diff":
                        payload = store.load_batch(project_dir, batch_no)
                        plan_a = body.get("plan_a") or {
                            "measurements": payload.get("proposal", {}).get("measurements", []),
                            "confirmed": payload.get("confirmed", [])}
                        plan_b = body.get("plan_b") or {
                            "measurements": payload.get("proposal", {}).get("measurements", []),
                            "confirmed": body.get("confirmed", [])}
                        v0 = store.load_version(project_dir, 0)
                        old_columns = _columns(v0["rows"])
                        plan_a["old_columns"] = old_columns
                        plan_b["old_columns"] = old_columns
                        diff = schema_mapping.compare_plans(
                            plan_a, plan_b, payload["raw_rows"], old_columns,
                            spec={"steps": body.get("steps", [])})
                        return self._send(200, diff)
                    confirmations = body.get("confirmed", [])
                    result = store.confirm_mappings(
                        project_dir, batch_no, confirmations,
                        replace=bool(body.get("replace", False)))
                    return self._send(200, {"ok": True, **result})
                if len(parts) == 7 and parts[3] == "batches" and parts[5] == "mappings":
                    if parts[6] != "revoke":
                        return self._send(404, {"error": "not found"})
                    batch_no = int(parts[4])
                    mapping_id = body.get("mapping_id")
                    result = store.revoke_mapping(
                        project_dir, batch_no, mapping_id)
                    exceptions = exc_store.load_exceptions(project_dir)
                    mapping = next((m for m in result["proposal"]["measurements"]
                                    if m["id"] == mapping_id), {})
                    affected = schema_mapping.dependent_exception_scopes(
                        exceptions, batch_no, mapping)
                    exc_store.mark_needs_recheck(project_dir, affected)
                    exceptions = exc_store.load_exceptions(project_dir)
                    return self._send(200, {
                        "ok": True, **result,
                        "dependent_decisions": [
                            {"key": key, "status": "needs_recheck",
                             "exception": exceptions[key]}
                            for key in affected],
                    })
                if len(parts) == 5 and parts[3] == "exceptions":
                    row_id = body["row_id"]
                    scope = body["scope"]
                    if parts[4] == "revoke":
                        exc_store.revoke_exception(project_dir, row_id, scope)
                    else:
                        exc_store.set_exception(
                            project_dir, row_id, scope, body["action"],
                            replacement=body.get("replacement"),
                            reason=body.get("reason", ""),
                            batch=body.get("batch"),
                            mapping_id=body.get("mapping_id"))
                    return self._send(200, {
                        "ok": True,
                        "exceptions": exc_store.load_exceptions(project_dir),
                    })
                if len(parts) == 4 and parts[3] == "rule-impact":
                    work_rows_all, _, appended_all, _ = store.working_rows_extended(project_dir)
                    appended_ids = {a["_id"] for a in appended_all}
                    step_type = body.get("step_type", "number_check")
                    impact = analysis.rule_impact(
                        body.get("old_params", {}), body.get("new_params", {}),
                        work_rows_all, step_type=step_type,
                        columns=body.get("columns"),
                        exceptions=exc_store.load_exceptions(project_dir))
                    for item in impact["changed_decisions"]:
                        item["is_new_row"] = item["row_id"] in appended_ids
                    for item in impact["newly_handled"]:
                        item["is_new_row"] = item["row_id"] in appended_ids
                    return self._send(200, impact)
                if len(parts) == 4 and parts[3] == "diff":
                    version_a = store.load_version(project_dir,
                                                  int(body["version_a"]))
                    version_b = store.load_version(project_dir,
                                                  int(body["version_b"]))
                    return self._send(200, analysis.version_diff(
                        version_a, version_b))
                latest = store.load_version(project_dir, manifest["latest_version"])
                if len(parts) == 4 and parts[3] == "preview":
                    spec = {"steps": body.get("steps", [])}
                    source_no = body.get("source_version", manifest["latest_version"])
                    use_workspace = bool(body.get("include_appended", False))
                    structure_actions = []
                    adopted_scope = {"status": "selected_version"}
                    if source_no == 0 and use_workspace:
                        structure_actions, adopted_scope = _structure_context(
                            work_rows, schema_batches)
                        source = {"rows": work_rows, "lineage": work_lineage,
                                  "structure_actions": structure_actions}
                    else:
                        source = (latest if source_no == manifest["latest_version"]
                                  else store.load_version(project_dir, int(source_no)))
                    exceptions = (exc_store.active_map(
                        exc_store.load_exceptions(project_dir))
                        if body.get("use_exceptions", True) else None)
                    rows, lineage, reports = pipeline.run(
                        source["rows"], spec,
                        base_lineage=source.get("lineage"),
                        exceptions=exceptions)
                    return self._send(200, {
                        "reports": reports,
                        "row_count_before": len(source["rows"]),
                        "row_count_after": len(rows),
                        "sample": rows,
                        "structure_actions": source.get("structure_actions", []),
                        "adopted_scope": adopted_scope,
                        "unresolved_mappings": adopted_scope.get("pending_mappings", []),
                    })
                if len(parts) == 4 and parts[3] == "apply":
                    spec = {"steps": body.get("steps", [])}
                    source_version = body.get("source_version")
                    work_rows, work_lineage, _, schema_batches = (
                        store.working_rows_extended(project_dir))
                    if (int(source_version if source_version is not None else manifest["latest_version"]) == 0
                            and body.get("include_appended", False)):
                        fresh_manifest = store.load_manifest(project_dir)
                        structure_actions, adopted_scope = _structure_context(
                            work_rows, schema_batches)
                        # Apply over the extended working set without
                        # rewriting v0: write a transient source snapshot.
                        source_version = self._snapshot_workspace(
                            project_dir, fresh_manifest, work_rows, work_lineage,
                            structure_actions=structure_actions,
                            adopted_scope=adopted_scope)
                    exceptions = (exc_store.active_map(
                        exc_store.load_exceptions(project_dir))
                        if body.get("use_exceptions", True) else None)
                    new_no, reports = pipeline.apply_spec(
                        project_dir, spec, label=body.get("label", ""),
                        source_version=(int(source_version)
                                       if source_version is not None else None),
                        exceptions=exceptions)
                    return self._send(201, {
                        "version": new_no,
                        "reports": reports,
                        "adopted_scope": adopted_scope if 'adopted_scope' in locals() else {"status": "selected_version"},
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
