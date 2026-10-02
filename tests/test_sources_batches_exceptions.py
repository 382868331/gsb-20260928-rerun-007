"""Source-scoped rules, batch append, manual exceptions and comparison."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import exceptions as manual_exc, pipeline, store
from backend.decisions import exception_conflicts


# Two sources feed the SAME illegal text "ERR" into the same column:
# lab-A must drop the row, lab-B must replace it. A single global rule
# could not express that and would wrongly numeric-ise the excluded row.
CSV = (
    "sample_id,lab,temperature\n"
    "S1,lab-A,25\n"
    "S2,lab-A,ERR\n"   # illegal -> drop for lab-A
    "S3,lab-B,ERR\n"   # illegal -> replace for lab-B
    "S4,lab-B,1000\n"  # out of range -> flag for lab-B
)

POLICIES = {
    "illegal": {"action": "drop"},
    "out_of_range": {"action": "drop"},
    "missing": {"action": "flag"},
    "by_source": {
        "lab-B": {
            "illegal": {"action": "replace", "replacement": 20},
            "out_of_range": {"action": "flag"},
        },
    },
}


def spec(policies=None, **extra):
    params = {"columns": ["temperature"], "min_value": 0,
              "max_value": 100, "source_column": "lab",
              "policies": policies or POLICIES}
    params.update(extra)
    return {"steps": [{"type": "number_check", "params": params}]}


class SourceRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_illegal_text_decided_per_source(self):
        rows, _, reports = pipeline.run(
            store.load_working(self.pdir)["rows"], spec())
        by_id = {r["_id"]: r for r in rows}
        self.assertNotIn("r0002", by_id)          # lab-A row excluded
        self.assertEqual(20, by_id["r0003"]["temperature"])  # lab-B replaced
        self.assertEqual("1000", by_id["r0004"]["temperature"])
        self.assertIn("temperature:out_of_range",
                      by_id["r0004"]["_review"])

        stats = reports[0]["stats"]
        by_source = stats["issue_actions_by_source"]["非法文字"]["by_source"]
        self.assertIn("排除该行", by_source["lab-A"])
        self.assertIn("使用替代值", by_source["lab-B"])
        details = {d["row_id"]: d
                   for d in stats["affected_rows"] if d["issue"] == "illegal"}
        self.assertEqual("global", details["r0002"]["decision_scope"])
        self.assertEqual("lab-A", details["r0002"]["source"])
        self.assertEqual("source:lab-B", details["r0003"]["decision_scope"])


class BatchAndExceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_batch_preview_splits_old_and_new_and_publishes(self):
        generation, new_rows, old_rows, _ = store.append_batch(
            self.tmp.name, "lab",
            "sample_id,lab,temperature\nS5,lab-A,ERR\nS6,lab-B,22\n",
            label="batch2")
        self.assertEqual(2, generation)
        self.assertEqual(2, len(new_rows))
        self.assertEqual(4, len(old_rows))
        # Published v1 must not be overwritten by the appended data:
        # nothing has been published yet beyond v0, working.json holds 6.
        self.assertEqual(0, store.load_manifest(self.pdir)["latest_version"])
        working = store.load_working(self.pdir)
        self.assertEqual(6, len(working["rows"]))
        self.assertEqual(["r0005", "r0006"],
                         [r["_id"] for r in new_rows])

        rows, _, reports = pipeline.run(working["rows"], spec())
        details = {d["row_id"]: d
                   for d in reports[0]["stats"]["affected_rows"]}
        # The new lab-A illegal row is excluded under the existing rule.
        self.assertEqual("drop_row", details["r0005"]["action"])
        self.assertNotIn("r0005", {r["_id"] for r in rows})

        new_no, _ = pipeline.apply_spec(self.pdir, spec())
        version = store.load_version(self.pdir, new_no)
        self.assertEqual(2, version["data_generation"])
        self.assertEqual(4, len(version["rows"]))
        # Appending again never overwrites the published version.
        store.append_batch(self.tmp.name, "lab",
                           "sample_id,lab,temperature\nS7,lab-B,23\n")
        self.assertEqual(1, store.load_manifest(self.pdir)["latest_version"])
        still = store.load_version(self.pdir, 1)
        self.assertEqual(4, len(still["rows"]))

    def test_manual_exception_overrides_rule_then_conflicts_on_rule_change(self):
        # Manually keep lab-A r0002 (illegal, normally dropped) flagged.
        rows, _, reports = pipeline.run(
            store.load_working(self.pdir)["rows"], spec())
        key = "r0002|temperature|number_check|illegal"
        fingerprint = reports[0]["stats"][
            "current_rule_fingerprints"][key]
        decision = manual_exc.add_exception(self.pdir, {
            "row_id": "r0002", "column": "temperature",
            "issue": "illegal", "stage": "number_check",
            "action": "replace", "replacement": 33,
        }, fingerprint)

        manual = manual_exc.active_decisions(self.pdir)
        rows, _, reports = pipeline.run(
            store.load_working(self.pdir)["rows"], spec(),
            context={"manual_decisions": manual})
        by_id = {r["_id"]: r for r in rows}
        self.assertEqual(33, by_id["r0002"]["temperature"])
        details = {d["row_id"]: d
                   for d in reports[0]["stats"]["affected_rows"]}
        self.assertTrue(details["r0002"]["manual"])
        self.assertEqual("manual", details["r0002"]["decision_scope"])

        # Change the rule for lab-A from drop to flag: the exception's
        # saved fingerprint now disagrees -> conflict reported.
        changed_policies = {
            "illegal": {"action": "flag"},
            "out_of_range": {"action": "drop"},
            "missing": {"action": "flag"},
            "by_source": {"lab-B": POLICIES["by_source"]["lab-B"]},
        }
        _, _, reports_new = pipeline.run(
            store.load_working(self.pdir)["rows"],
            spec(changed_policies))
        current = reports_new[0]["stats"]["rule_fingerprints"]
        conflicts = exception_conflicts(
            [decision],
            {decision["id"]: reports_new[0]["stats"][
                "current_rule_fingerprints"][key]})
        self.assertEqual(1, len(conflicts))
        # User keeps the exception: rebound to the new rule fingerprint.
        new_fingerprint = reports_new[0]["stats"][
            "current_rule_fingerprints"][key]
        manual_exc.resolve_conflicts(
            self.pdir, {decision["id"]: "keep"},
            {decision["id"]: new_fingerprint})
        kept = [d for d in manual_exc.load_exceptions(self.pdir)["decisions"]
                if d["id"] == decision["id"]][0]
        self.assertEqual("active", kept["status"])
        self.assertEqual(new_fingerprint, kept["rule_fingerprint"])

    def test_withdraw_exception_reinstates_rule_and_keeps_audit(self):
        working = store.load_working(self.pdir)
        rows, _, reports = pipeline.run(working["rows"], spec())
        key = "r0002|temperature|number_check|illegal"
        fingerprint = reports[0]["stats"][
            "current_rule_fingerprints"][key]
        decision = manual_exc.add_exception(self.pdir, {
            "row_id": "r0002", "column": "temperature",
            "issue": "illegal", "stage": "number_check",
            "action": "flag",
        }, fingerprint)
        manual = manual_exc.active_decisions(self.pdir)
        rows, _, _ = pipeline.run(working["rows"], spec(),
                                  context={"manual_decisions": manual})
        self.assertIn("r0002", {r["_id"] for r in rows})

        manual_exc.withdraw_exception(self.pdir, decision["id"])
        rows, _, _ = pipeline.run(
            working["rows"], spec(),
            context={"manual_decisions": manual_exc.active_decisions(
                self.pdir)})
        self.assertNotIn("r0002", {r["_id"] for r in rows})
        record = [d for d in manual_exc.load_exceptions(self.pdir)[
            "decisions"] if d["id"] == decision["id"]][0]
        self.assertEqual("withdrawn", record["status"])
        # audit still carries the original raw-value handling context
        self.assertEqual("ERR", CSV.splitlines()[2].split(",")[-1])


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_compare_separates_data_rules_and_manual_decisions(self):
        from backend import compare
        # v1: global drop for lab-B illegal (no source overrides).
        global_drop = {
            "illegal": {"action": "drop"},
            "out_of_range": {"action": "flag"},
            "missing": {"action": "flag"},
        }
        v1, _ = pipeline.apply_spec(
            self.pdir, spec(global_drop), label="strict")

        # Append a batch, then v2 uses the source-scoped rule.
        store.append_batch(
            self.tmp.name, "lab",
            "sample_id,lab,temperature\nS7,lab-B,ERR\n")
        v2, _ = pipeline.apply_spec(self.pdir, spec(), label="source-rules")
        result = compare.compare_versions(self.pdir, v1, v2)
        self.assertTrue(result["rules_changed"])
        # r0005 is the appended origin; r0003 differs due to the rule.
        self.assertIn("r0005", result["data_added_origins"])
        rule_cols = {(tuple(c["origins"]), c["column"])
                     for c in result["attributed_changes"]["rule_changed"]}
        self.assertIn(("r0003",), {o for o, _ in rule_cols})


if __name__ == "__main__":
    unittest.main()
