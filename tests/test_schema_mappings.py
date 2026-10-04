"""Schema-evolution measurement mapping and rule-inheritance tests."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import mappings, server, store
from tests.test_followup_api import call


OLD_CSV = (
    "sample_id,temperature,temp_unit,source\n"
    "A1,77,F,lab-A\n"
    "B1,25,C,lab-B\n"
    "C1,ERR,C,lab-A\n"
)

STEPS = [{
    "type": "unit_convert",
    "params": {
        "column": "temperature",
        "unit_column": "temp_unit",
        "canonical_unit": "C",
        "rules": {"C": 1, "F": {"factor": 0.5555556,
                                    "offset": -17.777778}},
        "policies": {"temperature": [
            {"issue": "illegal", "action": "flag",
             "value_matches": ["ERR"], "source_column": "source",
             "sources": ["lab-A"]},
        ]},
    },
}]


class SchemaMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        server.PROJECTS_ROOT = self.tmp.name
        call("POST", "/api/projects", {"name": "p", "csv": OLD_CSV})

    def tearDown(self):
        self.tmp.cleanup()

    def test_split_value_unit_requires_confirmation_and_preserves_text(self):
        status, res = call("POST", "/api/projects/p/batches/append", {
            "label": "new",
            "csv": "sample_id,temperature_value,temp_unit,source\n"
                   "D1,86,F,lab-A\n",
        })
        self.assertEqual(201, status)
        status, analysis_result = call("POST", "/api/projects/p/batch-mappings/1",
                                       {"steps": STEPS})
        self.assertEqual(200, status)
        proposal = analysis_result["mappings"][0]
        self.assertEqual("needs_mapping", proposal["rule_inheritance"])
        self.assertEqual(["temperature_value"], proposal["candidate_columns"])
        self.assertEqual("per_row", proposal["unit_mode"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status)
        self.assertEqual(["r0004"], [r["_id"] for r in preview["unmapped_rows"]])
        self.assertNotIn("r0004", {r["_id"] for r in preview["sample"]})

        status, _ = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temp_unit",
        })
        self.assertEqual(201 if False else 200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0,
            "include_appended": True,
        })
        new_row = next(r for r in preview["sample"] if r["_id"] == "r0004")
        self.assertAlmostEqual(30.0, new_row["temperature"], delta=0.01)
        self.assertEqual("86", new_row["_raw_temperature"])
        self.assertEqual("F", new_row["_raw_temperature_unit"])
        self.assertEqual(["b1:temperature"],
                         preview["adopted_scope"]["confirmed_mapping_ids"])
        mapping_report = preview["reports"][0]
        self.assertEqual("结构测量对应", mapping_report["label"])

    def test_ambiguous_mapping_is_not_auto_selected(self):
        old_cols = ["temperature"]
        new_cols = ["temperature_core", "temperature_surface"]
        rows = [{"_id": "r0009", "temperature_core": "1",
                 "temperature_surface": "2"}]
        result = mappings.analyze_schema(old_cols, new_cols, rows, batch_no=2)
        proposal = result["mappings"][0]
        self.assertEqual("ambiguous", proposal["status"])
        self.assertEqual(["temperature_core", "temperature_surface"],
                         proposal["candidate_columns"])
        self.assertFalse(proposal["confirmed"])

    def test_revoke_mapping_rechecks_manual_exception_and_publish_scope(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temp_unit,source\n"
                   "D1,86,F,lab-A\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temp_unit",
        })
        project_dir = os.path.join(self.tmp.name, "p")
        exc = {}
        exc.update(server.exc_store.set_exception(
            project_dir, "r0004",
            "unit_convert:temperature:post:out_of_range", "flag",
            reason="check this source measurement"))
        for item in exc.values():
            item["mapping_id"] = "b1:temperature"
        server.exc_store.save_exceptions(project_dir, exc)

        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(200, status)
        self.assertEqual({("r0004", "unit_convert:temperature:post:out_of_range")},
                         {(x["row_id"], x["scope"])
                          for x in res["affected_decisions"]})
        reopened = server.exc_store.load_exceptions(project_dir)
        self.assertFalse(next(iter(reopened.values()))["active"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual([], preview["adopted_scope"]["confirmed_mapping_ids"])
        self.assertEqual(["r0004"], [r["_id"] for r in preview["unmapped_rows"]])

    def test_persisted_mapping_trace_is_available_after_reopen(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temp_unit,source\n"
                   "D1,86,F,lab-A\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temp_unit",
        })
        status, info = call("GET", "/api/projects/p")
        self.assertEqual(200, status)
        self.assertIn("b1:temperature", info["mappings"])

        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": STEPS, "source_version": 0,
            "include_appended": True, "label": "mapped",
        })
        self.assertEqual(201, status)
        path = os.path.join(self.tmp.name, "p", "versions",
                            f"v{applied['version']}.json")
        saved = json.load(open(path, encoding="utf-8"))
        self.assertEqual("schema_mapping", saved["step_reports"][0]["type"])
        status, lineage = call("GET", "/api/projects/p/versions/"
                                      f"{applied['version']}/lineage/r0004")
        self.assertEqual(200, status)
        self.assertIn("结构对应", lineage["timeline"][0]["description"])

    def test_manual_exception_is_bound_to_mapping_and_record(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temp_unit,source\n"
                   "D1,9999,F,lab-A\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temp_unit",
        })
        bounded_steps = [{
            "type": "unit_convert",
            "params": {**STEPS[0]["params"],
                       "post_max_value": 100,
                       "post_policies": {"temperature": [
                           {"issue": "out_of_range", "action": "drop"}]}},
        }]
        # An old row+scope key can never control the newly mapped r0004.
        project_dir = os.path.join(self.tmp.name, "p")
        server.exc_store.set_exception(
            project_dir, "r0004",
            "unit_convert:temperature:post:out_of_range", "flag")
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": bounded_steps, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status)
        self.assertNotIn("r0004", {r["_id"] for r in preview["sample"]})

        status, _ = call("POST", "/api/projects/p/exceptions/set", {
            "row_id": "r0004",
            "scope": "unit_convert:temperature:post:out_of_range",
            "action": "flag", "mapping_id": "b1:temperature",
        })
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": bounded_steps, "source_version": 0,
            "include_appended": True,
        })
        self.assertIn("r0004", {r["_id"] for r in preview["sample"]})

    def test_renamed_value_and_unit_columns_reach_legacy_rule(self):
        # Both the value column and the unit column were renamed; the
        # confirmed interpretation must still feed the legacy unit rule.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temperature_unit,source\n"
                   "D1,147,F,lab-A\n"
                   "E1,-4,F,lab-B\n",
        })
        status, analysis_result = call("POST", "/api/projects/p/batch-mappings/1",
                                       {"steps": STEPS})
        self.assertEqual(200, status)
        proposal = analysis_result["mappings"][0]
        self.assertEqual("needs_mapping", proposal["rule_inheritance"])
        self.assertIn("temperature_unit", proposal["unit_candidates"])

        status, _ = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
        })
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(63.8889, rows["r0004"]["temperature"], places=3)
        self.assertAlmostEqual(-20.0, rows["r0005"]["temperature"], places=3)
        self.assertEqual("F", rows["r0004"]["_raw_temperature_unit"])
        self.assertEqual("per_row", rows["r0004"]["_raw_temperature_unit_source"])
        self.assertEqual("147", rows["r0004"]["_raw_temperature"])
        trace = preview["reports"][0]["actions"][0]["detail"]
        self.assertEqual("temp_unit", trace["legacy_unit_column"])

    def test_per_row_and_default_units_distinguish_blank_cells(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temperature_unit,source\n"
                   "D1,86,F,lab-A\n"
                   "E1,30,,lab-B\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
            "default_unit": "C",
        })
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(30.0, rows["r0004"]["temperature"], delta=0.01)
        self.assertEqual("per_row", rows["r0004"]["_raw_temperature_unit_source"])
        # Blank unit cell falls back to the batch default (C), not to F.
        self.assertAlmostEqual(30.0, rows["r0005"]["temperature"], delta=0.01)
        self.assertEqual("default", rows["r0005"]["_raw_temperature_unit_source"])
        self.assertEqual("C", rows["r0005"]["_raw_temperature_unit"])

    def test_renamed_columns_default_unit_values_and_persisted_basis(self):
        exact_steps = [{
            "type": "unit_convert",
            "params": {**STEPS[0]["params"], "rules": {
                "C": 1,
                "F": {"factor": 5 / 9, "offset": -160 / 9}}},
        }]
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom\n"
                   "X1,147,F\n"
                   "X2,-4,F\n"
                   "X3,32,\n",
        })
        status, analysis_result = call("POST", "/api/projects/p/batch-mappings/1",
                                       {"steps": exact_steps})
        self.assertEqual(200, status)
        proposal = analysis_result["mappings"][0]
        self.assertEqual("needs_mapping", proposal["status"])
        self.assertEqual(["reading"], proposal["candidate_columns"])
        self.assertEqual(["uom"], proposal["unit_candidates"])

        status, _ = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "reading",
            "unit_column": "uom",
            "default_unit": " F ",
        })
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": exact_steps, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(63.888889, rows["r0004"]["temperature"], places=6)
        self.assertEqual(-20.0, rows["r0005"]["temperature"])
        self.assertEqual(0.0, rows["r0006"]["temperature"])
        self.assertEqual("per_row", rows["r0004"]["_raw_temperature_unit_source"])
        self.assertEqual("default", rows["r0006"]["_raw_temperature_unit_source"])
        self.assertEqual("F", rows["r0006"]["_raw_temperature_unit"])
        mapping_actions = preview["reports"][0]["actions"]
        blank_trace = next(
            a for a in mapping_actions
            if a["origins"] == ["r0006"] and "temperature" in a["description"])
        self.assertIn("该行为空", blank_trace["description"])
        self.assertIn("整列默认单位 F", blank_trace["description"])

        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": exact_steps, "source_version": 0,
            "include_appended": True, "label": "renamed",
        })
        self.assertEqual(201, status)
        saved = server.store.load_version(
            os.path.join(self.tmp.name, "p"), applied["version"])
        saved_rows = {r["_id"]: r for r in saved["rows"]}
        self.assertAlmostEqual(63.888889,
                               saved_rows["r0004"]["temperature"], places=6)
        self.assertEqual(0.0, saved_rows["r0006"]["temperature"])
        status, lineage = call("GET", "/api/projects/p/versions/"
                                      f"{applied['version']}/lineage/r0006")
        self.assertEqual(200, status)
        self.assertTrue(any("整列默认单位 F" in item["description"]
                            for item in lineage["timeline"]))

    def test_explicit_unknown_unit_is_not_replaced_by_default(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom\nX1,32,BOGUS\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "reading",
            "unit_column": "uom",
            "default_unit": "F",
        })
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(400, status)
        self.assertIn("BOGUS", preview["error"])

    def test_revoke_is_scoped_to_its_own_batch_with_same_column_names(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom\nX1,147,F\n",
        })
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom\nY1,100,C\n",
        })
        for batch in (1, 2):
            status, _ = call(
                "POST", f"/api/projects/p/batch-mappings/{batch}/confirm", {
                    "target_column": "temperature",
                    "value_column": "reading",
                    "unit_column": "uom",
                    **({"default_unit": "F"} if batch == 1 else {}),
                })
            self.assertEqual(200, status)
        status, res = call("POST", "/api/projects/p/batch-mappings/2/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(400, status)
        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b2:temperature"})
        self.assertEqual(400, status)
        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(200, status)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        self.assertEqual(["r0004"], [r["_id"] for r in preview["unmapped_rows"]])
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertEqual(100.0, rows["r0005"]["temperature"])
        self.assertEqual(["b2:temperature"],
                         preview["adopted_scope"]["confirmed_mapping_ids"])

    def test_same_column_name_from_two_sources_does_not_overwrite(self):
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom,source\n"
                   "D1,86,F,lab-A\n"
                   "E1,30,C,lab-B\n",
        })
        for sources in (["lab-A"], ["lab-B"]):
            status, res = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
                "target_column": "temperature",
                "value_column": "reading",
                "unit_column": "uom",
                "source_column": "source",
                "sources": sources,
            })
            self.assertEqual(200, status)
        status, info = call("GET", "/api/projects/p")
        saved = [m for m in info["mappings"].values()
                 if m["target_column"] == "temperature"]
        self.assertEqual(2, len(saved))
        self.assertEqual({("lab-A",), ("lab-B",)},
                         {tuple(m["sources"]) for m in saved})
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(30.0, rows["r0004"]["temperature"], delta=0.01)
        self.assertAlmostEqual(30.0, rows["r0005"]["temperature"], delta=0.01)

    def test_partial_confirm_then_publish_scope_matches_across_batches(self):
        # Batch 1: only one of two measurements confirmed -> partial scope.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temperature_unit,source\n"
                   "D1,147,F,lab-A\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
        })
        # Batch 2: value column merged back to the legacy name.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature,temp_unit,source\n"
                   "E1,-4,F,lab-B\n",
        })
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        scope = preview["adopted_scope"]
        self.assertEqual(["b1:temperature", "b2:temperature:auto"],
                         scope["confirmed_mapping_ids"])
        published_ids = set(scope["published_row_ids"])
        self.assertIn("r0004", published_ids)
        self.assertIn("r0005", published_ids)  # implicit same-name reuse

        # Reopen from disk: saved mapping must still drive the same scope.
        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(201, status, applied)
        final = server.store.load_version(
            os.path.join(self.tmp.name, "p"), applied["version"])
        rows = {r["_id"]: r for r in final["rows"]}
        self.assertAlmostEqual(63.8889, rows["r0004"]["temperature"], places=3)
        self.assertAlmostEqual(-20.0, rows["r0005"]["temperature"], places=3)
        # Preview scope and final published scope are the same rows.
        self.assertEqual(published_ids,
                         {r["_id"] for r in final["rows"]
                          if r.get("_mapping_status") == "confirmed"})

        # Revoking the unit mapping reopens only dependent decisions and
        # never rewrites the published version.
        before = json.dumps(final["rows"], sort_keys=True)
        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(200, status)
        reloaded = server.store.load_version(
            os.path.join(self.tmp.name, "p"), applied["version"])
        self.assertEqual(before, json.dumps(reloaded["rows"], sort_keys=True))
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(["r0004"], [r["_id"] for r in preview["unmapped_rows"]])


if __name__ == "__main__":
    unittest.main()
