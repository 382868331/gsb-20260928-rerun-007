"""End-to-end API test without a real socket.

Drives http.server.BaseHTTPRequestHandler through a fake stream pair,
so routing, JSON encoding and error paths all run for real.
"""
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import server


class FakeConnection:
    def __init__(self, body=b""):
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()

    def makefile(self, *args, **kwargs):
        return self.rfile if "r" in args[0] else self.wfile


def call(method, path, payload=None, data_root=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    connection = FakeConnection(body)
    handler = object.__new__(server.Handler)
    handler.rfile = connection.rfile
    handler.wfile = connection.wfile
    handler.headers = {"Content-Length": str(len(body))} if body else {}
    handler.command = method
    handler.path = path
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.client_address = ("test", 0)
    handler.server = type("S", (), {"server_version": "X"})()
    handler._send_calls = []
    if method == "GET":
        server.Handler.do_GET(handler)
    else:
        server.Handler.do_POST(handler)
    raw = connection.wfile.getvalue()
    head, _, content = raw.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    return status, json.loads(content)


CSV = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "examples", "mixed_units_duplicates.csv"),
    encoding="utf-8").read()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_flow(self):
        status, res = call("POST", "/api/projects", {"name": "lab", "csv": CSV})
        self.assertEqual(201, status)

        status, res = call("GET", "/api/projects/lab")
        self.assertEqual(200, status)
        self.assertEqual(8, res["row_count"])
        self.assertIn("temperature", res["columns"])

        spec = {
            "steps": [
                {"type": "unit_convert", "params": {
                    "column": "temperature", "unit_column": "temp_unit",
                    "canonical_unit": "C",
                    "rules": {"C": 1, "F": {
                        "factor": 0.5555555555555556,
                        "offset": -17.77777777777778}}}},
                {"type": "missing_values", "params": {
                    "columns": ["temperature", "pressure"],
                    "strategy": "fill_median"}},
                {"type": "dedup_merge", "params": {
                    "keys": ["sample_id"], "merge": "mean",
                    "on_conflict": "keep_all"}},
            ]
        }
        status, preview = call("POST", "/api/projects/lab/preview", spec)

        # The shipped sample deliberately contains an illegal numeric value
        # (S6 temperature 'ERR'): preview/apply must fail and publish nothing.
        self.assertEqual(400, status)
        self.assertIn("non-numeric", preview["error"])
        status, info = call("GET", "/api/projects/lab")
        self.assertEqual(0, info["manifest"]["latest_version"])
        status, failed = call("POST", "/api/projects/lab/apply", spec)
        self.assertEqual(400, status)
        self.assertIn("non-numeric", failed["error"])

        # Fix the raw value (100F -> valid), re-run: success is published and
        # can be reopened later.
        clean_csv = CSV.replace("S6,2026-09-05,ERR,F,100.1",
                                "S6,2026-09-05,100.0,F,100.1")
        call("POST", "/api/projects", {"name": "lab2", "csv": clean_csv})

        # preview exposes which rows each step touches (before publishing)
        status, prev = call("POST", "/api/projects/lab2/preview", spec)
        self.assertEqual(200, status)
        unit_affected = prev["reports"][0]["stats"]["affected_rows"]
        affected_ids = {row["row_id"] for row in unit_affected}
        self.assertIn("r0002", affected_ids)  # 77F
        self.assertIn("r0007", affected_ids)  # 212F

        status, applied = call("POST", "/api/projects/lab2/apply", spec)
        self.assertEqual(201, status)
        self.assertEqual(1, applied["version"])

        status, v1 = call("GET", "/api/projects/lab2/versions/1")
        self.assertEqual(200, status)
        self.assertEqual(6, len(v1["rows"]))

        s1 = next(r for r in v1["rows"] if r["sample_id"] == "S1")
        status, lineage = call(
            "GET", f"/api/projects/lab2/versions/1/lineage/{s1['_id']}")
        self.assertEqual(200, status)
        self.assertEqual(["r0001", "r0004"], lineage["origins"])
        self.assertEqual(2, len(lineage["origin_rows"]))
        descriptions = " ".join(item["description"] for item in lineage["timeline"])
        self.assertIn("重复合并", descriptions)

        # successful project can be reopened from disk
        status, info2 = call("GET", "/api/projects/lab2")
        self.assertEqual(200, status)
        self.assertEqual(1, info2["manifest"]["latest_version"])

    def test_failed_unit_step_returns_error_and_no_version(self):
        call("POST", "/api/projects", {"name": "lab", "csv": CSV})
        bad = {"steps": [{"type": "unit_convert", "params": {
            "column": "temperature", "unit_column": "temp_unit",
            "canonical_unit": "C", "rules": {"C": 1}}}]}
        status, res = call("POST", "/api/projects/lab/apply", bad)
        self.assertEqual(400, status)
        self.assertTrue("unknown unit" in res["error"]
                        or "non-numeric" in res["error"])
        status, info = call("GET", "/api/projects/lab")
        self.assertEqual(0, info["manifest"]["latest_version"])


if __name__ == "__main__":
    unittest.main()
