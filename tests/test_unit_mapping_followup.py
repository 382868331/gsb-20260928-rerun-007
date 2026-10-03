"""Follow-up: renamed value+unit columns, mixed units, per-source mappings."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import server
from backend.steps.unit_convert import apply as unit_convert_apply
from tests.test_followup_api import call


OLD_CSV = (
    "sample_id,temperature,temp_unit,source\n"
    "A1,77,F,lab-A\n"
    "B1,25,C,lab-B\n"
)

STEPS = [{
    "type": "unit_convert",
    "params": {
        "column": "temperature",
        "unit_column": "temp_unit",
        "canonical_unit": "C",
        "rules": {"C": 1, "F": {"factor": 0.5555556, "offset": -17.777778}},
    },
}]

BATCH1_CSV = (
    "sample_id,temperature_value,temperature_unit,source\n"
    "D1,147,F,lab-A\n"
    "D2,-4,F,lab-B\n"
    "D3,30,,lab-A\n"
)


class RenamedUnitColumnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name
        call("POST", "/api/projects", {"name": "p", "csv": OLD_CSV})
        call("POST", "/api/projects/p/batches/append",
             {"csv": BATCH1_CSV, "label": "renamed"})

    def tearDown(self):
        self.tmp.cleanup()

    def _confirm_batch1(self):
        status, res = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
            "default_unit": "C",
        })
        self.assertEqual(200, status)
        return res["mapping"]

    def _preview(self):
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status)
        return preview

    def test_renamed_value_and_unit_columns_convert_after_confirm(self):
        status, analysis = call("POST", "/api/projects/p/batch-mappings/1",
                                 {"steps": STEPS})
        self.assertEqual(200, status)
        proposal = analysis["mappings"][0]
        self.assertEqual("needs_mapping", proposal["rule_inheritance"])
        self.assertIn("temperature_unit", proposal["unit_candidates"])

        mapping = self._confirm_batch1()
        self.assertEqual("mixed", mapping["unit_mode"])

        preview = self._preview()
        rows = {r["_id"]: r for r in preview["sample"]}
        # 147 F -> 63.89 C, -4 F -> -20 C, blank unit -> default C stays 30.
        self.assertAlmostEqual(63.8889, rows["r0003"]["temperature"], places=3)
        self.assertAlmostEqual(-20.0, rows["r0004"]["temperature"], places=3)
        self.assertAlmostEqual(30.0, rows["r0005"]["temperature"], places=3)
        # The legacy unit column receives the resolved unit and ends canonical.
        for rid in ("r0003", "r0004", "r0005"):
            self.assertEqual("C", rows[rid]["temp_unit"])
        # Original text and unit basis stay auditable on the row.
        self.assertEqual("147", rows["r0003"]["_raw_temperature"])
        self.assertEqual("F", rows["r0003"]["_raw_temperature_unit"])
        self.assertEqual("", rows["r0005"]["_raw_temperature_unit"])
        self.assertEqual(["b1:temperature"],
                         preview["adopted_scope"]["confirmed_mapping_ids"])
        self.assertEqual([], preview["unmapped_rows"])
        report = preview["reports"][1]
        self.assertEqual("unit_convert", report["type"])
        trace = {a["detail"]["row_id"]: a["detail"]
                 for a in preview["reports"][0]["actions"]}
        self.assertEqual("per_row", trace["r0003"]["unit_source"])
        self.assertEqual("default", trace["r0005"]["unit_source"])
        self.assertEqual("temp_unit", trace["r0003"]["legacy_unit_column"])

    def test_partial_confirm_then_publish_scope_matches_preview(self):
        self._confirm_batch1()
        # A second, still unconfirmed batch must not enter preview or publish.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temperature_unit,source\n"
                   "E1,50,F,lab-A\n",
        })
        preview = self._preview()
        self.assertEqual(["r0006"],
                         [r["_id"] for r in preview["unmapped_rows"]])
        self.assertEqual("pending",
                         preview["unmapped_rows"][0]["_mapping_status"])
        self.assertEqual(["temperature"],
                         preview["unmapped_rows"][0]["_missing_targets"])
        preview_ids = {r["_id"] for r in preview["sample"]}
        self.assertNotIn("r0006", preview_ids)

        # Reopen (state lives on disk) and confirm the second batch too.
        status, info = call("GET", "/api/projects/p")
        self.assertEqual(200, status)
        self.assertIn("b1:temperature", info["mappings"])
        status, _ = call("POST", "/api/projects/p/batch-mappings/2/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
        })
        self.assertEqual(200, status)

        preview = self._preview()
        self.assertEqual([], preview["unmapped_rows"])
        self.assertEqual({"b1:temperature", "b2:temperature"},
                         set(preview["adopted_scope"]["confirmed_mapping_ids"]))
        adopted = set(preview["adopted_scope"]["published_row_ids"])
        self.assertEqual({"r0003", "r0004", "r0005", "r0006"}, adopted)

        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
            "label": "both batches",
        })
        self.assertEqual(201, status)
        path = os.path.join(self.tmp.name, "p", "versions",
                            f"v{applied['version']}.json")
        published = json.load(open(path, encoding="utf-8"))
        published_ids = {r["_id"] for r in published["rows"]}
        self.assertEqual({r["_id"] for r in preview["sample"]}, published_ids)
        self.assertEqual(adopted,
                         {r["_id"] for r in published["rows"]
                          if r.get("_mapping_status") == "confirmed"})
        rows = {r["_id"]: r for r in published["rows"]}
        self.assertAlmostEqual(10.0, rows["r0006"]["temperature"], places=3)

    def test_same_columns_two_sources_do_not_overwrite(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,source\n"
                   "E1,10,lab-A\n"
                   "E2,50,lab-B\n",
        })
        for source, default in (("lab-A", "C"), ("lab-B", "F")):
            status, res = call("POST", "/api/projects/p/batch-mappings/2/confirm", {
                "target_column": "temperature",
                "value_column": "temperature_value",
                "default_unit": default,
                "source_column": "source",
                "sources": [source],
            })
            self.assertEqual(200, status)
        self.assertIn("b2:temperature:source=lab-A", res["mappings"])
        self.assertIn("b2:temperature:source=lab-B", res["mappings"])

        self._confirm_batch1()
        preview = self._preview()
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(10.0, rows["r0006"]["temperature"], places=3)
        self.assertAlmostEqual(10.0, rows["r0006"]["temperature"], places=3)
        self.assertEqual("C", rows["r0006"]["temp_unit"])
        self.assertEqual("C", rows["r0007"]["temp_unit"])
        self.assertEqual("F", rows["r0007"]["_raw_temperature_unit"])

    def test_revoke_reopens_only_dependents_and_keeps_published(self):
        self._confirm_batch1()
        project_dir = os.path.join(self.tmp.name, "p")
        server.exc_store.set_exception(
            project_dir, "r0003",
            "unit_convert:temperature:post:out_of_range", "flag",
            reason="bound to mapping", mapping_id="b1:temperature")
        server.exc_store.set_exception(
            project_dir, "r0001",
            "unit_convert:temperature:post:out_of_range", "flag",
            reason="old row, no mapping")

        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
            "label": "published",
        })
        self.assertEqual(201, status)

        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(200, status)
        self.assertEqual(["r0003"],
                         [x["row_id"] for x in res["affected_decisions"]])
        exceptions = server.exc_store.load_exceptions(project_dir)
        by_row = {item["row_id"]: item for item in exceptions.values()}
        self.assertFalse(by_row["r0003"]["active"])
        self.assertTrue(by_row["r0001"]["active"])

        # Published version keeps original text, unit basis and result.
        path = os.path.join(self.tmp.name, "p", "versions",
                            f"v{applied['version']}.json")
        published = json.load(open(path, encoding="utf-8"))
        row = next(r for r in published["rows"] if r["_id"] == "r0003")
        self.assertAlmostEqual(63.8889, row["temperature"], places=3)
        self.assertEqual("147", row["_raw_temperature"])
        self.assertEqual("F", row["_raw_temperature_unit"])
        self.assertEqual("C", row["temp_unit"])

        # After revoke the batch-1 rows are unmapped again in preview.
        preview = self._preview()
        self.assertEqual({"r0003", "r0004", "r0005"},
                         {r["_id"] for r in preview["unmapped_rows"]})
        self.assertEqual([], preview["adopted_scope"]["confirmed_mapping_ids"])


class UnitClassificationTests(unittest.TestCase):
    def test_blank_unknown_and_explicit_units_are_distinct(self):
        rows = [
            {"_id": "r1", "temperature": "20", "temp_unit": ""},
            {"_id": "r2", "temperature": "68", "temp_unit": "F"},
        ]
        out, _, stats = unit_convert_apply(rows, {
            "column": "temperature", "unit_column": "temp_unit",
            "canonical_unit": "C",
            "rules": {"F": {"factor": 0.5555556, "offset": -17.777778}},
        })
        self.assertEqual(1, stats["blank_unit_rows"])
        self.assertEqual(20.0, out[0]["temperature"])
        self.assertAlmostEqual(20.0, out[1]["temperature"], places=3)

        with self.assertRaises(ValueError) as ctx:
            unit_convert_apply(
                [{"_id": "r3", "temperature": "5", "temp_unit": "K"}],
                {"column": "temperature", "unit_column": "temp_unit",
                 "canonical_unit": "C", "rules": {}})
        self.assertIn("K", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
