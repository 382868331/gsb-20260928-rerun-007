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
    os.path.abspath(__file__))), "examples", "mixed_units_duplicates_clean.csv"),
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
        self.assertEqual(7, res["row_count"])
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
        self.assertEqual(200, status)
        self.assertEqual(5, preview["row_count_after"])
        self.assertIn("converted_rows", preview["reports"][0]["stats"])

        # preview must not create a version
        status, info = call("GET", "/api/projects/lab")
        self.assertEqual(0, info["manifest"]["latest_version"])

        status, applied = call("POST", "/api/projects/lab/apply", spec)
        self.assertEqual(201, status)
        self.assertEqual(1, applied["version"])

        status, v1 = call("GET", "/api/projects/lab/versions/1")
        self.assertEqual(200, status)
        self.assertEqual(5, len(v1["rows"]))

        s1 = next(r for r in v1["rows"] if r["sample_id"] == "S1")
        status, lineage = call(
            "GET", f"/api/projects/lab/versions/1/lineage/{s1['_id']}")
        self.assertEqual(200, status)
        self.assertEqual(["r0001", "r0004"], lineage["origins"])
        self.assertEqual(2, len(lineage["origin_rows"]))

    def test_failed_unit_step_returns_error_and_no_version(self):
        call("POST", "/api/projects", {"name": "lab", "csv": CSV})
        bad = {"steps": [{"type": "unit_convert", "params": {
            "column": "temperature", "unit_column": "temp_unit",
            "canonical_unit": "C", "rules": {"C": 1}}}]}
        status, res = call("POST", "/api/projects/lab/apply", bad)
        self.assertEqual(400, status)
        self.assertIn("unknown unit", res["error"])
        status, info = call("GET", "/api/projects/lab")
        self.assertEqual(0, info["manifest"]["latest_version"])

    def test_illegal_value_aborts_preview_and_apply_without_publish(self):
        bad_csv = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "examples",
            "mixed_units_duplicates.csv"), encoding="utf-8").read()
        call("POST", "/api/projects", {"name": "bad", "csv": bad_csv})
        spec = {"steps": [
            {"type": "unit_convert", "params": {
                "column": "temperature", "unit_column": "temp_unit",
                "canonical_unit": "C",
                "rules": {"C": 1, "F": {
                    "factor": 0.5555555555555556,
                    "offset": -17.77777777777778}}}},
        ]}
        status, res = call("POST", "/api/projects/bad/preview", spec)
        self.assertEqual(400, status)
        self.assertIn("non-numeric", res["error"])
        self.assertIn("r0008", res["error"])
        status, res = call("POST", "/api/projects/bad/apply", spec)
        self.assertEqual(400, status)
        status, info = call("GET", "/api/projects/bad")
        self.assertEqual(0, info["manifest"]["latest_version"])

    def test_preview_stages_and_lineage_treatments(self):
        call("POST", "/api/projects", {"name": "lab", "csv": CSV})
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
        self.assertEqual(200, status)
        self.assertEqual(3, len(preview["stages"]))
        self.assertEqual(7, preview["stages"][0]["row_count"])
        self.assertEqual(5, preview["stages"][2]["row_count"])
        converted = preview["reports"][0]["stats"]["affected_row_ids"]
        self.assertIn("r0002", converted)

        call("POST", "/api/projects/lab/apply", spec)
        status, v1 = call("GET", "/api/projects/lab/versions/1")
        s2 = next(r for r in v1["rows"] if r["sample_id"] == "S2")
        status, trace = call(
            "GET", f"/api/projects/lab/versions/1/lineage/{s2['_id']}")
        self.assertEqual(200, status)
        actions = {(t["step"], t["action"]) for t in trace["treatments"]}
        self.assertIn((1, "converted"), actions)
        self.assertIn((3, "merged"), actions)
        merge_step = next(t for t in trace["treatments"] if t["action"] == "merged")
        self.assertEqual(["r0002", "r0005"],
                         merge_step["detail"]["source_row_ids"])

    def test_samples_endpoint(self):
        status, res = call("GET", "/api/samples/bad")
        self.assertEqual(200, status)
        self.assertIn("hot", res["csv"])
        status, res = call("GET", "/api/samples/clean")
        self.assertEqual(200, status)
        self.assertNotIn("hot", res["csv"])


if __name__ == "__main__":
    unittest.main()
