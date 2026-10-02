"""Follow-up regression: per-source decisions, batch append, consistency.

Covers the report: when the same illegal text comes from two sources,
each source decision must take effect independently; preview, stats and
published rows must agree; unit conversion keeps the same per-source
behaviour; manual exceptions survive withdraw with full per-row
correspondence of raw value, converted value and drop reason.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import exceptions as manual_exc, pipeline, store


CSV = (
    "sample_id,lab,temperature,temp_unit\n"
    "S1,lab-A,77,F\n"      # 25 C
    "S2,lab-A,ERR,F\n"     # illegal, drop for lab-A
    "S3,lab-B,ERR,F\n"     # illegal, replace for lab-B
    "S4,lab-B,212,F\n"     # 100 C -> post out of range for [0,40]
)

POLICIES = {
    "illegal": {"action": "drop"},
    "out_of_range": {"action": "drop"},
    "missing": {"action": "flag"},
    "by_source": {
        "lab-B": {
            "illegal": {"action": "replace", "replacement": 20},
        },
    },
}
POST_POLICIES = {
    "out_of_range": {"action": "flag"},
    "by_source": {
        "lab-A": {"out_of_range": {"action": "drop"}},
    },
}


def spec():
    return {"steps": [{"type": "unit_convert", "params": {
        "column": "temperature", "unit_column": "temp_unit",
        "canonical_unit": "C",
        "rules": {"F": {"factor": 0.5555556, "offset": -17.777778}},
        "post_max_value": 40,
        "source_column": "lab",
        "policies": POLICIES,
        "post_policies": POST_POLICIES,
    }}]}


class PerSourceUnitConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_stats_and_publish_agree_per_source(self):
        working = store.load_working(self.pdir)
        preview_rows, _, reports = pipeline.run(working["rows"], spec())
        stats = reports[0]["stats"]
        details = {d["row_id"]: d
                   for d in stats["affected_rows"] if d.get("issue")}
        # lab-A illegal row is excluded; lab-B illegal row is replaced.
        self.assertEqual("drop_row", details["r0002"]["action"])
        self.assertEqual("global", details["r0002"]["decision_scope"])
        self.assertEqual("replace", details["r0003"]["action"])
        self.assertEqual("source:lab-B",
                         details["r0003"]["decision_scope"])
        # Post-conversion range: global flag (lab-B S4) vs lab-A override.
        self.assertEqual("flag", details["r0004"]["action"])
        by_pre = stats["issue_actions_by_source"]["pre_convert"]
        self.assertIn("排除该行",
                      by_pre["非法文字"]["by_source"]["lab-A"])
        self.assertIn("使用替代值",
                      by_pre["非法文字"]["by_source"]["lab-B"])

        # Published version must equal the in-memory preview exactly.
        new_no, published_reports = pipeline.apply_spec(self.pdir, spec())
        version = store.load_version(self.pdir, new_no)
        self.assertEqual(
            [(r["_id"], r["temperature"]) for r in preview_rows],
            [(r["_id"], r["temperature"]) for r in version["rows"]])
        published_stats = published_reports[0]["stats"]
        self.assertEqual(
            stats["issue_actions_by_source"],
            published_stats["issue_actions_by_source"])
        by_id = {r["_id"]: r for r in version["rows"]}
        self.assertNotIn("r0002", by_id)
        self.assertEqual(20, by_id["r0003"]["temperature"])
        # S4 converted 100 C, flagged rather than dropped.
        self.assertAlmostEqual(100.0, float(by_id["r0004"]["temperature"]),
                               places=4)
        self.assertIn("temperature:out_of_range",
                      by_id["r0004"]["_review"])

    def test_append_then_withdraw_keeps_row_correspondence(self):
        # Publish once, append a new batch; the published version stays.
        v1, _ = pipeline.apply_spec(self.pdir, spec(), label="first")
        store.append_batch(
            self.tmp.name, "lab",
            "sample_id,lab,temperature,temp_unit\n"
            "S5,lab-A,ERR,F\nS6,lab-B,22,C\n",
            label="batch2")
        self.assertEqual(
            len(store.load_version(self.pdir, v1)["rows"]), 3)

        working = store.load_working(self.pdir)
        rows, _, reports = pipeline.run(working["rows"], spec())
        details = {d["row_id"]: d
                   for d in reports[0]["stats"]["affected_rows"]}
        self.assertEqual("drop_row", details["r0005"]["action"])
        self.assertNotIn("r0005", {r["_id"] for r in rows})

        # Manual exception keeps the new row; then withdraw -> dropped
        # again, with original value / drop reason still recorded.
        key = "r0005|temperature|pre_convert|illegal"
        fingerprint = reports[0]["stats"][
            "current_rule_fingerprints"][key]
        decision = manual_exc.add_exception(self.pdir, {
            "row_id": "r0005", "column": "temperature",
            "issue": "illegal", "stage": "pre_convert",
            "action": "flag",
        }, fingerprint)
        manual = manual_exc.active_decisions(self.pdir)
        rows2, _, reports2 = pipeline.run(
            working["rows"], spec(),
            context={"manual_decisions": manual})
        self.assertIn("r0005", {r["_id"] for r in rows2})

        manual_exc.withdraw_exception(self.pdir, decision["id"])
        rows3, _, reports3 = pipeline.run(
            working["rows"], spec(), context={
                "manual_decisions": manual_exc.active_decisions(self.pdir)})
        self.assertNotIn("r0005", {r["_id"] for r in rows3})
        drop_detail = next(
            d for d in reports3[0]["stats"]["affected_rows"]
            if d["row_id"] == "r0005")
        self.assertEqual("ERR", drop_detail["original_value"])
        self.assertEqual("F", drop_detail["unit"])
        self.assertEqual("drop_row", drop_detail["action"])
        audit = [d for d in manual_exc.load_exceptions(self.pdir)[
            "decisions"] if d["id"] == decision["id"]][0]
        self.assertEqual("withdrawn", audit["status"])


if __name__ == "__main__":
    unittest.main()
