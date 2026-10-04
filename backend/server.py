"""Stdlib-only JSON API for the cleaning workbench.

Run:  python3 -m backend.server --port 8000
Data lives in <root>/projects (default: ./data/projects).
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import analysis, exceptions as exc_store, mappings as mapping_lib, pipeline, store


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

    def _snapshot_workspace(self, project_dir, manifest, rows, lineage):
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
            "kind": "batch_append",
        }
        pipeline.atomic_write_json(
            os.path.join(project_dir, "versions", f"v{new_no}.json"),
            payload)
        manifest["versions"].append({
            "version": new_no, "created_from": 0,
            "label": "追加实验批次", "steps": [], "reports": [],
            "kind": "batch_append",
        })
        manifest["latest_version"] = new_no
        pipeline.atomic_write_json(
            os.path.join(project_dir, "manifest.json"), manifest)
        return new_no

    def _mapping_exception_status(self, project_dir, mappings):
        exceptions = exc_store.load_exceptions(project_dir)
        affected = []
        for key, item in exceptions.items():
            mapping_id = item.get("mapping_id")
            if mapping_id and any(m["id"] == mapping_id for m in mappings):
                affected.append({"key": key, "active": item.get("active", True),
                                 "row_id": item.get("row_id"),
                                 "scope": item.get("scope"),
                                 "mapping_id": mapping_id})
        return affected

    def _revoke_dependent_decisions(self, project_dir, mapping_id):
        exceptions = exc_store.load_exceptions(project_dir)
        affected = []
        for key, item in list(exceptions.items()):
            if item.get("mapping_id") != mapping_id:
                continue
            item["active"] = False
            item["revoked_by_mapping"] = True
            affected.append({"row_id": item.get("row_id"),
                             "scope": item.get("scope")})
        exc_store.save_exceptions(project_dir, exceptions)
        return affected

    def _adoption_scope(self, rows, reports, workspace_used):
        mapping_ids = set()
        for report in reports:
            for action in report.get("actions", []):
                mid = action.get("detail", {}).get("mapping_id")
                if mid:
                    mapping_ids.add(mid)
        return {
            "workspace_appended_included": workspace_used,
            "confirmed_mapping_ids": sorted(mapping_ids),
            "published_row_ids": [row["_id"] for row in rows
                                   if row.get("_mapping_status") == "confirmed"],
            "note": "仅采用已确认测量对应关系覆盖的追加记录；未确认记录不进入发布版本。",
        }

    def _compare_mapping_plans(self, plans):
        result = []
        for index, plan in enumerate(plans):
            analysis_result = mapping_lib.analyze_schema(
                plan.get("old_columns", []), plan.get("new_columns", []),
                plan.get("rows", []), batch_no=plan.get("batch"),
                steps=plan.get("steps"))
            mappings = [mapping_lib.normalize_mapping(plan.get("batch", index + 1), m)
                        for m in plan.get("mappings", [])]
            result.append({
                "name": plan.get("name", f"方案 {index + 1}"),
                "structure": {
                    "added": analysis_result["added_columns"],
                    "removed": analysis_result["removed_columns"],
                    "explanation": [p["reason"] for p in analysis_result["mappings"]],
                },
                "cleaning_rules": [
                    {"target": p["target_column"], "status": p["rule_inheritance"],
                     "rules": p["rules"]}
                    for p in analysis_result["mappings"]],
                "data_added": {"row_ids": [r.get("_id") for r in plan.get("rows", [])],
                                "count": len(plan.get("rows", []))},
                "confirmed_mappings": mappings,
            })
        return {"plans": result}

    def _adapted_workspace(self, project_dir, work_rows, work_lineage, appended,
                           include_pending=True, steps=None):
        v0 = store.load_version(project_dir, 0)
        old_columns = list(dict.fromkeys(key for row in v0["rows"]
                                         for key in row
                                         if not key.startswith("_")))
        explicit_records = list(store.load_mappings(project_dir).values())
        implicit_records = mapping_lib.implicit_reusable_mappings(
            old_columns, appended, work_rows, steps or [])
        records = explicit_records + [m for m in implicit_records
                                      if not any(e.get("batch") == m.get("batch")
                                                 and e.get("target_column") == m.get("target_column")
                                                 for e in explicit_records)]
        required_targets = set(mapping_lib.rule_targets(steps or []))
        legacy_unit_columns = {}
        for target, refs in mapping_lib.rule_targets(steps or []).items():
            for ref in refs:
                if ref.get("unit_column"):
                    legacy_unit_columns[target] = ref["unit_column"]
        rows, pending, traces = mapping_lib.apply_mappings(
            work_rows, appended, records, old_columns,
            required_targets=required_targets,
            legacy_unit_columns=legacy_unit_columns)
        adapted_lineage = {row["_id"]: [row["_id"]] for row in rows}
        pre_report = {
            "type": "schema_mapping",
            "label": "结构测量对应",
            "params": {"mapping_ids": sorted({m["id"] for m in records})},
            "stats": {"confirmed_rows": len(set(traces)),
                       "pending_rows": len(pending),
                       "affected_rows": [item["detail"] for item
                                          in mapping_lib.mapping_trace_report(traces)]},
            "row_count_before": len(work_rows),
            "row_count_after": len(rows),
            "actions": mapping_lib.mapping_trace_report(traces),
        }
        return rows, adapted_lineage, pending, pre_report

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
                        "appended": store.working_rows(project_dir)[2],
                        "mappings": store.load_mappings(project_dir),
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
                work_rows, work_lineage, appended = store.working_rows(project_dir)
                if len(parts) == 5 and parts[3] == "batches":
                    result = store.append_batch(
                        PROJECTS_ROOT, name, body.get("csv", ""),
                        batch_label=body.get("label", ""))
                    return self._send(201, {
                        "ok": True, "batch": result["batch"],
                        "new_ids": result["new_ids"],
                        "new_rows": result["new_rows"],
                    })
                if (len(parts) == 5 and parts[3] == "batch-mappings"):
                    batch_no = int(parts[4])
                    v0 = store.load_version(project_dir, 0)
                    raw_rows, _, appended = store.working_rows(project_dir)
                    meta = [item for item in appended if item.get("batch") == batch_no]
                    if not meta:
                        raise ValueError(f"batch {batch_no} not found")
                    columns = meta[0].get("columns") or []
                    rows = [row for row in raw_rows
                            if row.get("_id") in {m["_id"] for m in meta}]
                    old_columns = list(dict.fromkeys(key for row in v0["rows"]
                                                     for key in row
                                                     if not key.startswith("_")))
                    steps = body.get("steps") or []
                    existing = [m for m in store.load_mappings(project_dir).values()
                                if m.get("batch") == batch_no]
                    result = mapping_lib.analyze_schema(
                        old_columns, columns, rows, batch_no=batch_no,
                        steps=steps)
                    result["confirmed_mappings"] = existing
                    result["exceptions"] = self._mapping_exception_status(
                        project_dir, existing)
                    return self._send(200, result)
                if (len(parts) == 6 and parts[3] == "batch-mappings"
                        and parts[5] == "confirm"):
                    batch_no = int(parts[4])
                    mapping = mapping_lib.normalize_mapping(batch_no, body)
                    saved = store.save_mapping(project_dir, mapping)
                    return self._send(200, {"ok": True, "mapping": mapping,
                                            "mappings": saved})
                if (len(parts) == 6 and parts[3] == "batch-mappings"
                        and parts[5] == "revoke"):
                    mapping_id = body.get("id") or body.get("mapping_id")
                    saved = store.revoke_mapping(project_dir, mapping_id)
                    affected = self._revoke_dependent_decisions(project_dir, mapping_id)
                    return self._send(200, {"ok": True, "mappings": saved,
                                            "affected_decisions": affected})
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
                            mapping_id=body.get("mapping_id"))
                    return self._send(200, {
                        "ok": True,
                        "exceptions": exc_store.load_exceptions(project_dir),
                    })
                if len(parts) == 4 and parts[3] == "rule-impact":
                    work_rows_all, _, appended_all = store.working_rows(project_dir)
                    appended_ids = {a["_id"] for a in appended_all}
                    step_type = body.get("step_type", "number_check")
                    if appended_all:
                        impact_step = {
                            "type": step_type,
                            "params": body.get("new_params", {}),
                        }
                        work_rows_all, _, _, _ = self._adapted_workspace(
                            project_dir, work_rows_all,
                            {r["_id"]: [r["_id"]] for r in work_rows_all},
                            appended_all, include_pending=False,
                            steps=[impact_step])
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
                if len(parts) == 4 and parts[3] == "mapping-schemas":
                    plans = body.get("plans") or []
                    return self._send(200, self._compare_mapping_plans(plans))
                latest = store.load_version(project_dir, manifest["latest_version"])
                if len(parts) == 4 and parts[3] == "preview":
                    spec = {"steps": body.get("steps", [])}
                    source_no = body.get("source_version", manifest["latest_version"])
                    use_workspace = bool(body.get("include_appended", False))
                    pre_reports = None
                    pending = []
                    if source_no == 0 and use_workspace:
                        source_rows, source_lineage, pending, pre_report = self._adapted_workspace(
                            project_dir, work_rows, work_lineage, appended,
                            include_pending=bool(body.get("include_unmapped", False)),
                            steps=body.get("steps"))
                        source = {"rows": source_rows, "lineage": source_lineage}
                        pre_reports = [pre_report]
                    else:
                        source = (latest if source_no == manifest["latest_version"]
                                  else store.load_version(project_dir, int(source_no)))
                    exceptions = (exc_store.active_map(
                        exc_store.load_exceptions(project_dir))
                        if body.get("use_exceptions", True) else None)
                    rows, lineage, reports = pipeline.run(
                        source["rows"], spec,
                        base_lineage=source.get("lineage"),
                        exceptions=exceptions, pre_reports=pre_reports)
                    return self._send(200, {
                        "reports": reports,
                        "row_count_before": len(work_rows) if use_workspace and source_no == 0 else len(source["rows"]),
                        "row_count_after": len(rows),
                        "sample": rows,
                        "unmapped_rows": pending if use_workspace and source_no == 0 else [],
                        "adopted_scope": self._adoption_scope(rows, reports,
                                                                use_workspace and source_no == 0),
                    })
                if len(parts) == 4 and parts[3] == "apply":
                    spec = {"steps": body.get("steps", [])}
                    source_version = body.get("source_version")
                    pre_reports = None
                    if (int(source_version or manifest["latest_version"]) == 0
                            and body.get("include_appended", False)):
                        adapted_rows, adapted_lineage, pending, pre_report = self._adapted_workspace(
                            project_dir, work_rows, work_lineage, appended,
                            include_pending=False, steps=body.get("steps"))
                        if pending:
                            raise ValueError(
                                "存在尚未确认测量对应关系的追加记录；本次不能把它们纳入发布范围")
                        source_version = self._snapshot_workspace(
                            project_dir, manifest, adapted_rows, adapted_lineage)
                        pre_reports = [pre_report]
                    exceptions = (exc_store.active_map(
                        exc_store.load_exceptions(project_dir))
                        if body.get("use_exceptions", True) else None)
                    new_no, reports = pipeline.apply_spec(
                        project_dir, spec, label=body.get("label", ""),
                        source_version=(int(source_version)
                                       if source_version is not None else None),
                        exceptions=exceptions, pre_reports=pre_reports)
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
