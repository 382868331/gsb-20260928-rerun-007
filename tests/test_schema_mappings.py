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

    def test_default_unit_fills_only_blank_rows_explicit_unknown_rejected(self):
        # 147F -> 63.89C, -4F -> -20C, blank unit on 32 falls back to the
        # column default (C), and an explicit but unregistered unit (X)
        # keeps following the original unknown-unit rejection path.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,temperature_value,temperature_unit,source\n"
                   "D1,147,F,lab-A\n"
                   "E1,-4,F,lab-B\n"
                   "F1,32,,lab-A\n"
                   "G1,9,X,lab-B\n",
        })
        status, res = call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
            "default_unit": "C",
        })
        self.assertEqual(200, status, res)
        status, info = call("GET", "/api/projects/p")
        saved = info["mappings"]["b1:temperature"]
        self.assertEqual("C", saved["default_unit"])
        self.assertEqual("temperature_unit", saved["unit_column"])

        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(400, status)
        self.assertIn("unknown unit", preview["error"])
        self.assertIn("X", preview["error"])
        self.assertIn("r0007", preview["error"])
        # The blank row alone is not called out: default applies to it.
        self.assertNotIn("r0006", preview["error"])

        # Without a default unit, the blank row is also rejected,
        # and the message says why (blank + no default).
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
        })
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(400, status)
        self.assertIn("r0006", preview["error"])
        self.assertIn("默认单位", preview["error"])

        # Re-confirm restores the default; normal rows then convert.
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "temperature_value",
            "unit_column": "temperature_unit",
            "default_unit": "C",
        })
        steps_without_unknown = [{
            "type": "unit_convert",
            "params": {**STEPS[0]["params"],
                       "rules": {"C": 1, "F": {"factor": 0.5555556,
                                                 "offset": -17.777778},
                                 "X": 1}},
        }]
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": steps_without_unknown, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(63.8889, rows["r0004"]["temperature"], places=3)
        self.assertAlmostEqual(-20.0, rows["r0005"]["temperature"], places=3)
        self.assertAlmostEqual(32.0, rows["r0006"]["temperature"], places=3)
        self.assertEqual("per_row", rows["r0004"]["_raw_temperature_unit_source"])
        self.assertEqual("per_row", rows["r0005"]["_raw_temperature_unit_source"])
        self.assertEqual("default", rows["r0006"]["_raw_temperature_unit_source"])
        self.assertEqual("per_row", rows["r0007"]["_raw_temperature_unit_source"])

        # Publish: the persisted step action records the unit source per row,
        # so reopening the project still explains explicit vs default units.
        status, applied = call("POST", "/api/projects/p/apply", {
            "steps": steps_without_unknown, "source_version": 0,
            "include_appended": True,
        })
        self.assertEqual(201, status, applied)
        version_path = os.path.join(self.tmp.name, "p", "versions",
                                   f"v{applied['version']}.json")
        published = json.load(open(version_path, encoding="utf-8"))
        details = {(a["origins"][0], a["detail"]["unit_source"])
                   for a in published["step_reports"][0]["actions"]}
        self.assertIn(("r0004", "per_row"), details)
        self.assertIn(("r0006", "default"), details)
        default_action = next(a for a in published["step_reports"][0]["actions"]
                              if a["origins"][0] == "r0006")
        self.assertIn("整列默认单位", default_action["description"])
        explicit_action = next(a for a in published["step_reports"][0]["actions"]
                               if a["origins"][0] == "r0004")
        self.assertIn("显式单位", explicit_action["description"])
        status, lineage = call("GET", "/api/projects/p/versions/"
                                      f"{applied['version']}/lineage/r0006")
        self.assertEqual(200, status)
        self.assertIn("默认单位", lineage["timeline"][0]["description"])

    def test_default_unit_decisions_are_independent_across_batches(self):
        # Two batches both use the generic column names reading/uom, but
        # their defaults differ and must be stored/resolved independently.
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom,source\n"
                   "D1,32,,lab-A\n",
        })
        call("POST", "/api/projects/p/batches/append", {
            "csv": "sample_id,reading,uom,source\n"
                   "E1,32,,lab-A\n",
        })
        call("POST", "/api/projects/p/batch-mappings/1/confirm", {
            "target_column": "temperature",
            "value_column": "reading",
            "unit_column": "uom",
            "default_unit": "C",
        })
        call("POST", "/api/projects/p/batch-mappings/2/confirm", {
            "target_column": "temperature",
            "value_column": "reading",
            "unit_column": "uom",
            "default_unit": "F",
        })
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(200, status, preview)
        rows = {r["_id"]: r for r in preview["sample"]}
        self.assertAlmostEqual(32.0, rows["r0004"]["temperature"], places=3)
        self.assertAlmostEqual(0.0, rows["r0005"]["temperature"], places=3)
        self.assertEqual("C", rows["r0004"]["_raw_temperature_unit"])
        self.assertEqual("F", rows["r0005"]["_raw_temperature_unit"])
        self.assertEqual("default", rows["r0004"]["_raw_temperature_unit_source"])
        self.assertEqual("default", rows["r0005"]["_raw_temperature_unit_source"])

        # Revoking batch 1 leaves batch 2's default intact and only r0004
        # drops back to pending.
        status, res = call("POST", "/api/projects/p/batch-mappings/1/revoke",
                           {"id": "b1:temperature"})
        self.assertEqual(200, status, res)
        status, preview = call("POST", "/api/projects/p/preview", {
            "steps": STEPS, "source_version": 0, "include_appended": True,
        })
        self.assertEqual(["r0004"], [r["_id"] for r in preview["unmapped_rows"]])
        status, info = call("GET", "/api/projects/p")
        remaining = [m for m in info["mappings"].values()
                     if m["target_column"] == "temperature"]
        self.assertEqual([2], [m["batch"] for m in remaining])
        self.assertEqual("F", remaining[0]["default_unit"])

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
