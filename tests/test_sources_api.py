"""HTTP-level coverage for source rules, batches, exceptions, compare."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import server
from tests.test_api import call


CSV = (
    "sample_id,lab,temperature\n"
    "S1,lab-A,25\nS2,lab-A,ERR\n"
    "S3,lab-B,ERR\nS4,lab-B,1000\n"
)

POLICIES = {
    "illegal": {"action": "drop"},
    "out_of_range": {"action": "drop"},
    "missing": {"action": "flag"},
    "by_source": {"lab-B": {
        "illegal": {"action": "replace", "replacement": 20},
        "out_of_range": {"action": "flag"}}},
}

SPEC = {"steps": [{"type": "number_check", "params": {
    "columns": ["temperature"], "min_value": 0, "max_value": 100,
    "source_column": "lab", "policies": POLICIES}}]}


class SourceApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_exception_conflict_and_compare(self):
        status, _ = call("POST", "/api/projects",
                         {"name": "lab", "csv": CSV})
        self.assertEqual(201, status)

        # Append a new batch under the same source rules.
        status, res = call("POST", "/api/projects/lab/batches", {
            "csv": "sample_id,lab,temperature\nS5,lab-A,ERR\n",
            "label": "batch2"})
        self.assertEqual(201, status)
        self.assertEqual(2, res["generation"])
        self.assertEqual(["r0005"], res["batch"]["row_ids"])

        # Preview reports old and new record counts and source decisions.
        status, preview = call("POST", "/api/projects/lab/preview", SPEC)
        self.assertEqual(200, status)
        self.assertEqual(4, preview["old_record_count"])
        self.assertEqual(1, preview["new_record_count"])
        details = {d["row_id"]: d
                   for r in preview["reports"]
                   for d in r["stats"]["affected_rows"]}
        self.assertEqual("global", details["r0002"]["decision_scope"])
        self.assertEqual("source:lab-B",
                         details["r0003"]["decision_scope"])
        self.assertTrue(details["r0005"]["is_new"])

        # Create a manual exception for r0002 (preview fingerprint first).
        status, dry = call("POST", "/api/projects/lab/exceptions", {
            **SPEC, "row_id": "r0002", "column": "temperature",
            "issue": "illegal", "stage": "number_check",
            "action": "replace", "replacement": 40, "dry_run": True})
        self.assertEqual(200, status)
        self.assertTrue(dry["rule_fingerprint"])
        status, created = call("POST", "/api/projects/lab/exceptions", {
            **SPEC, "row_id": "r0002", "column": "temperature",
            "issue": "illegal", "stage": "number_check",
            "action": "replace", "replacement": 40})
        self.assertEqual(201, status)
        exception_id = created["exception"]["id"]

        # Change lab-A rule from drop to flag: publish blocked with 409.
        changed = {"steps": [{"type": "number_check", "params": {
            "columns": ["temperature"], "min_value": 0, "max_value": 100,
            "source_column": "lab", "policies": {
                "illegal": {"action": "flag"},
                "out_of_range": {"action": "drop"},
                "missing": {"action": "flag"},
                "by_source": {"lab-B": POLICIES["by_source"]["lab-B"]}}}}]}
        status, blocked = call("POST", "/api/projects/lab/apply", changed)
        self.assertEqual(409, status)
        self.assertEqual([exception_id], blocked["unresolved"])

        # User keeps the manual exception; publish succeeds.
        changed["conflict_resolutions"] = {exception_id: "keep"}
        status, published = call("POST", "/api/projects/lab/apply", changed)
        self.assertEqual(201, status)
        self.assertEqual(1, published["version"])

        # Withdraw the exception and publish again from working data.
        status, withdrawn = call(
            "POST", f"/api/projects/lab/exceptions/{exception_id}/withdraw")
        self.assertEqual(200, status)
        self.assertEqual("withdrawn", withdrawn["exception"]["status"])
        second = {key: value for key, value in changed.items()
                  if key != "conflict_resolutions"}
        status, published2 = call("POST", "/api/projects/lab/apply", second)
        self.assertEqual(201, status)

        # Withdrawing reinstates the new rule for that exact cell: the
        # global illegal policy is now flag, so raw ERR is kept marked.
        status, v2_rows = call("GET", "/api/projects/lab/versions/2")
        self.assertEqual(200, status)
        r2 = next(r for r in v2_rows["rows"] if r["_id"] == "r0002")
        self.assertEqual("ERR", r2["temperature"])
        self.assertIn("temperature:illegal", r2["_review"])

        # Comparison attributes the two versions' differences.
        status, comp = call("POST", "/api/projects/lab/compare/1/2", {})
        self.assertEqual(200, status)
        causes = {
            (tuple(c["origins"]), c["cause"])
            for bucket in comp["attributed_changes"].values()
            for c in bucket}
        manual = [o for (o, cause) in causes if cause == "manual_decision"]
        self.assertIn(("r0002",), manual)

        # Exception audit survives a reload from disk.
        status, listing = call("GET",
                              "/api/projects/lab/versions/0/exceptions")
        self.assertEqual(200, status)
        statuses = [d["status"] for d in listing["decisions"]]
        self.assertIn("withdrawn", statuses)


if __name__ == "__main__":
    unittest.main()
