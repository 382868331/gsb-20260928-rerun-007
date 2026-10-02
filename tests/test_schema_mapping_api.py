import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.test_followup_api import call
from backend import server


OLD_CSV = (
    "sample_id,temperature,temp_unit,source\n"
    "A1,ERR,C,lab-A\n"
    "B1,70,F,lab-B\n"
)

NEW_CSV = (
    "sample_id,temperature_value,temperature_unit,source\n"
    "C1,ERR,F,lab-A\n"
    "D1,86,F,lab-B\n"
)

STEPS = [{
    "type": "unit_convert",
    "params": {
        "column": "temperature",
        "unit_column": "temp_unit",
        "canonical_unit": "C",
        "rules": {"C": 1, "F": {"factor": 0.5555555555555556,
                                "offset": -17.77777777777778}},
        "policies": {
            "temperature": [
                {"issue": "illegal", "action": "drop",
                 "value_matches": ["ERR"],
                 "source_column": "source", "sources": ["lab-A"]},
            ],
        },
    },
}]


class SchemaMappingApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_confirmation_preview_lineage_and_revoke_recheck(self):
        call("POST", "/api/projects", {"name": "p", "csv": OLD_CSV})
        status, _ = call("POST", "/api/projects/p/apply", {
            "steps": STEPS, "source_version": 0, "label": "old rules",
        })
        self.assertEqual(201, status)
        status, append = call("POST", "/api/projects/p/batches/append", {
            "csv": NEW_CSV, "label": "split",
        })
        self.assertEqual(201, status)
        self.assertEqual("changed", append["schema_status"])
        proposal = append["proposal"]
        self.assertIn("batch-1-m2",
                      proposal["rule_classification"]["needs_correspondence"])
        self.assertEqual("temperature",
                         proposal["measurements"][1]["target_measurement"])
        self.assertEqual(["temperature_value", "temperature_unit"],
                         proposal["measurements"][1]["source_columns"])

        mapping_id = proposal["measurements"][1]["id"]
        status, confirmed = call(
            "POST", "/api/projects/p/batches/1/mappings",
            {"confirmed": [{
                "id": mapping_id,
                "target_measurement": "temperature",
                "target_unit_column": "temp_unit",
            }]})
        self.assertEqual(200, status)
        self.assertEqual([mapping_id], confirmed["confirmed_ids"])
        self.assertEqual([], confirmed["pending_ids"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS,
            "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status)
        self.assertEqual({"r0002", "r0004"},
                         {row["_id"] for row in preview["sample"]})
        self.assertEqual("complete", preview["adopted_scope"]["status"])
        self.assertEqual(0, len(preview["unresolved_mappings"]))
        row = next(row for row in preview["sample"] if row["_id"] == "r0004")
        self.assertEqual(30.0, row["temperature"])
        self.assertEqual("C", row["temp_unit"])
        self.assertIn("temperature_value",
                      preview["structure_actions"][0]["description"])

        scope = "unit_convert:temperature:pre:illegal"
        status, _ = call("POST", "/api/projects/p/exceptions/set", {
            "row_id": "r0003", "scope": scope, "action": "flag",
            "batch": 1, "mapping_id": mapping_id,
        })
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertIn("r0003", {row["_id"] for row in preview["sample"]})

        status, published = call("POST", "/api/projects/p/apply", {
            "steps": STEPS,
            "source_version": 0,
            "include_appended": True,
            "label": "confirmed mapping",
        })
        self.assertEqual(201, status)
        status, lineage = call(
            "GET",
            f"/api/projects/p/versions/{published['version']}/lineage/r0004")
        self.assertEqual(200, status)
        self.assertIn("结构对应", lineage["timeline"][0]["step"])

        status, revoke = call(
            "POST", "/api/projects/p/batches/1/mappings/revoke",
            {"mapping_id": mapping_id})
        self.assertEqual(200, status)
        self.assertEqual(scope,
                         revoke["dependent_decisions"][0]["exception"]["scope"])
        status, info = call("GET", "/api/projects/p")
        exception = next(item for item in info["exceptions"].values()
                         if item["row_id"] == "r0003")
        self.assertTrue(exception["needs_recheck"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS,
            "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status)
        preview_rows = {row["_id"]: row for row in preview["sample"]}
        self.assertIn("r0003", preview_rows)
        self.assertIn("temperature",
                      preview_rows["r0003"]["_unresolved_measurements"])
        self.assertTrue(preview["unresolved_mappings"])


if __name__ == "__main__":
    unittest.main()
