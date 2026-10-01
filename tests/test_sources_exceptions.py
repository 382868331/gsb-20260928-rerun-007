"""Per-source rules, batch append, manual exceptions and version diff."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import analysis, exceptions as exc, pipeline, store


CSV = (
    "sample_id,temperature,source\n"
    "A1,ERR,lab-A\n"   # r0001 illegal text from source A -> replace
    "B1,ERR,lab-B\n"   # r0002 same illegal text from source B -> drop
    "C1,25,lab-A\n"    # r0003 fine
)

PARAMS = {
    "columns": ["temperature"],
    "policies": {
        "temperature": [
            {"issue": "illegal", "action": "replace", "replacement": 20,
             "value_matches": ["ERR"], "source_column": "source",
             "sources": ["lab-A"], "label": "A源非法文字替代"},
            {"issue": "illegal", "action": "drop",
             "value_matches": ["ERR"], "source_column": "source",
             "sources": ["lab-B"], "label": "B源非法文字排除"},
            {"issue": "illegal", "action": "flag"},
        ],
    },
}
SPEC = {"steps": [{"type": "number_check", "params": PARAMS}]}


class SourceRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_illegal_text_decided_per_source(self):
        new_no, reports = pipeline.apply_spec(self.pdir, SPEC, label="per-source")
        rows = {r["_id"]: r
                for r in store.load_version(self.pdir, new_no)["rows"]}
        self.assertEqual(20, rows["r0001"]["temperature"])
        self.assertNotIn("r0002", rows)
        self.assertIn("r0003", rows)
        actions = {(a["detail"]["row_id"]): a["detail"]
                   for a in reports[0]["actions"]}
        self.assertEqual("replace", actions["r0001"]["action"])
        self.assertEqual("drop_row", actions["r0002"]["action"])
        self.assertEqual("lab-A", actions["r0001"]["source_value"])
        self.assertEqual("lab-B", actions["r0002"]["source_value"])

    def test_preview_matches_published_result(self):
        rows, _, reports = pipeline.run(
            store.load_version(self.pdir, 0)["rows"], SPEC)
        preview_ids = {r["_id"] for r in rows}
        new_no, _ = pipeline.apply_spec(self.pdir, SPEC)
        published = {r["_id"] for r in
                     store.load_version(self.pdir, new_no)["rows"]}
        self.assertEqual(preview_ids, published)
        stats = reports[0]["stats"]
        self.assertEqual(1, stats["rows_dropped"])
        self.assertEqual(1, stats["cells_replaced"])


class BatchAndExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")
        self.scope = pipeline.scope_for(
            "number_check", "temperature", "illegal", "check")

    def tearDown(self):
        self.tmp.cleanup()

    def _active(self):
        return exc.active_map(exc.load_exceptions(self.pdir))

    def test_append_batch_does_not_rewrite_published_versions(self):
        v1_no, _ = pipeline.apply_spec(self.pdir, SPEC, label="v1")
        v1_before = open(os.path.join(self.pdir, "versions", "v1.json"),
                         "rb").read()
        result = store.append_batch(
            self.tmp.name, "lab",
            "sample_id,temperature,source\nD1,ERR,lab-A\nE1,21,lab-B\n",
            batch_label="oct")
        self.assertEqual(["r0004", "r0005"], result["new_ids"])
        v1_after = open(os.path.join(self.pdir, "versions", "v1.json"),
                        "rb").read()
        self.assertEqual(v1_before, v1_after)
        rows, _, appended = store.working_rows(self.pdir)
        self.assertEqual(5, len(rows))
        self.assertEqual({"r0004", "r0005"},
                         {a["_id"] for a in appended})

    def test_manual_exception_overrides_then_revoke_restores_rule(self):
        exc.set_exception(self.pdir, "r0002", self.scope, "flag",
                          reason="人工保留")
        v_manual, reports = pipeline.apply_spec(
            self.pdir, SPEC, source_version=0,
            exceptions=self._active(), label="manual")
        rows = {r["_id"]: r
                for r in store.load_version(self.pdir, v_manual)["rows"]}
        self.assertIn("r0002", rows)
        self.assertIn("temperature:illegal", rows["r0002"]["_review"])
        manual = [d for d in reports[0]["stats"]["affected_rows"]
                  if d.get("manual")]
        self.assertEqual("r0002", manual[0]["row_id"])

        # reopen: exceptions persist on disk and keep the same decision
        reopened = exc.active_map(exc.load_exceptions(self.pdir))
        self.assertIn("r0002|" + self.scope, reopened)

        exc.revoke_exception(self.pdir, "r0002", self.scope)
        v_rule, _ = pipeline.apply_spec(
            self.pdir, SPEC, source_version=0,
            exceptions=self._active(), label="revoked")
        rows2 = {r["_id"]: r
                 for r in store.load_version(self.pdir, v_rule)["rows"]}
        self.assertNotIn("r0002", rows2)

    def test_rule_change_lists_affected_rows_and_conflicting_manual(self):
        exc.set_exception(self.pdir, "r0002", self.scope, "flag",
                          reason="人工保留")
        rows, _, _ = store.working_rows(self.pdir)
        new_params = {
            "columns": ["temperature"],
            "policies": {
                "temperature": [
                    {"issue": "illegal", "action": "replace",
                     "replacement": 20, "value_matches": ["ERR"],
                     "source_column": "source", "sources": ["lab-A"]},
                    {"issue": "illegal", "action": "replace",
                     "replacement": 15, "value_matches": ["ERR"],
                     "source_column": "source", "sources": ["lab-B"]},
                    {"issue": "illegal", "action": "flag"},
                ],
            },
        }
        impact = analysis.rule_impact(
            PARAMS, new_params, rows,
            exceptions=exc.load_exceptions(self.pdir))
        changed = {c["row_id"]: c for c in impact["changed_decisions"]}
        self.assertEqual("drop", changed["r0002"]["old_action"])
        self.assertEqual("replace", changed["r0002"]["new_action"])
        conflicts = {c["row_id"]: c
                     for c in impact["conflicting_exceptions"]}
        self.assertEqual("flag", conflicts["r0002"]["manual_action"])
        self.assertEqual("replace", conflicts["r0002"]["rule_action"])

    def test_diff_attributes_data_rules_and_manual_decisions(self):
        v_rule, _ = pipeline.apply_spec(self.pdir, SPEC, source_version=0)
        store.append_batch(
            self.tmp.name, "lab",
            "sample_id,temperature,source\nD1,ERR,lab-A\n")
        exc.set_exception(self.pdir, "r0002", self.scope, "flag")
        rows, lineage, _ = store.working_rows(self.pdir)
        v_new, lineage_out, reports_new = pipeline.run(
            rows, SPEC, base_lineage=lineage, exceptions=self._active())
        new_version = {"rows": v_new, "lineage": lineage,
                       "step_reports": reports_new}
        diff = analysis.version_diff(
            store.load_version(self.pdir, v_rule), new_version)
        # r0004 is genuinely new data; r0002 reappears because of the
        # manual decision, not because data was added, and must be
        # attributed to the manual cause instead.
        self.assertEqual(["r0004"], diff["data_added"])
        self.assertIn("r0002", diff["manual_rows"])
        # r0002 was dropped by the rule version and is restored (flag)
        # solely because of the manual exception decision
        self.assertIn("r0002", diff["restored_rows"])


if __name__ == "__main__":
    unittest.main()
