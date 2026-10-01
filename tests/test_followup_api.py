"""End-to-end follow-up flow: per-source rules, batches, exceptions."""
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


def call(method, path, payload=None):
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
    handler.server = type("S", (), {})()
    if method == "GET":
        server.Handler.do_GET(handler)
    else:
        server.Handler.do_POST(handler)
    raw = connection.wfile.getvalue()
    head, _, content = raw.partition(b"\r\n\r\n")
    return int(head.split(b" ")[1]), json.loads(content)


CSV = (
    "sample_id,temperature,source\n"
    "A1,ERR,lab-A\n"
    "B1,ERR,lab-B\n"
    "C1,25,lab-A\n"
)

SPEC_STEPS = [{
    "type": "number_check",
    "params": {
        "columns": ["temperature"],
        "policies": {
            "temperature": [
                {"issue": "illegal", "action": "replace", "replacement": 20,
                 "value_matches": ["ERR"], "source_column": "source",
                 "sources": ["lab-A"]},
                {"issue": "illegal", "action": "drop",
                 "value_matches": ["ERR"], "source_column": "source",
                 "sources": ["lab-B"]},
                {"issue": "illegal", "action": "flag"},
            ],
        },
    },
}]


class FollowupApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_source_preview_batch_exceptions_diff_revoke(self):
        status, _ = call("POST", "/api/projects",
                         {"name": "p", "csv": CSV})
        self.assertEqual(201, status)

        status, res = call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature,source\nD1,ERR,lab-A\n",
            "label": "oct",
        })
        self.assertEqual(201, status)
        self.assertEqual(["r0004"], res["new_ids"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": SPEC_STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status)
        self.assertEqual(
            {"r0001", "r0003", "r0004"},
            {r["_id"] for r in preview["sample"]})

        scope = "number_check:temperature:check:illegal"
        status, _ = call("POST", "/api/projects/p/exceptions/set", {
            "row_id": "r0002", "scope": scope, "action": "flag",
            "reason": "manual review",
        })
        self.assertEqual(200, status)

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": SPEC_STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(
            {"r0001", "r0002", "r0003", "r0004"},
            {r["_id"] for r in preview["sample"]})
        manual = [d for report in preview["reports"]
                  for d in report["stats"]["affected_rows"]
                  if d.get("manual")]
        self.assertTrue(any(d["row_id"] == "r0002" for d in manual))

        status, impact = call("POST", "/api/projects/p/rule-impact", {
            "step_type": "number_check",
            "columns": ["temperature"],
            "old_params": {"policies": {}},
            "new_params": SPEC_STEPS[0]["params"],
        })
        self.assertEqual(200, status)
        self.assertTrue(any(c["row_id"] == "r0002"
                            for c in impact["conflicting_exceptions"]))
        self.assertTrue(any(c["row_id"] == "r0004" and c["is_new_row"]
                            for c in impact["newly_handled"]))

        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": SPEC_STEPS, "source_version": 0,
            "include_appended": True, "label": "clean+batch",
        })
        self.assertEqual(201, status)
        # v0 (3 rows) remains byte-identical in row set
        v0_path = os.path.join(self.tmp.name, "p", "versions", "v0.json")
        v0 = json.load(open(v0_path, encoding="utf-8"))
        self.assertEqual(3, len(v0["rows"]))

        status, diff = call("POST", "/api/projects/p/diff",
                            {"version_a": 1, "version_b": applied["version"]})
        self.assertEqual(200, status)
        self.assertIn("r0002", diff["manual_rows"])
        self.assertIn("r0002", diff["restored_rows"])
        self.assertTrue(any(c["row_id"] == "r0004"
                            for c in diff["value_changed"]))

        # Reopen: exceptions and appended rows still listed.
        status, info = call("GET", "/api/projects/p")
        self.assertEqual(200, status)
        self.assertEqual(1, len(info["appended"]))
        self.assertIn("r0002|" + scope, info["exceptions"])

        status, _ = call("POST", "/api/projects/p/exceptions/revoke", {
            "row_id": "r0002", "scope": scope,
        })
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": SPEC_STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertNotIn("r0002",
                         {r["_id"] for r in preview["sample"]})


if __name__ == "__main__":
    unittest.main()
