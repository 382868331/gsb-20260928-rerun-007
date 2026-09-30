import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pipeline, store


CSV = (
    "sample_id,temperature,pressure\n"
    "S1,25,101\n"
    "S2,Infinity,100\n"      # non-finite text, must not become a number
    "S3,ERR,100\n"           # illegal text
    "S4,,100\n"              # missing
    "S5,999,100\n"           # out of configured finite range
)

CHECK_POLICIES = {
    "nonfinite": {"action": "drop"},
    "illegal": {"action": "replace", "replacement": 20},
    "out_of_range": {"action": "flag"},
    "missing": {"action": "flag"},
}


class NumberCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, **overrides):
        params = {
            "columns": ["temperature"],
            "min_value": -50, "max_value": 100,
            "policies": CHECK_POLICIES,
        }
        params.update(overrides)
        return {"steps": [{"type": "number_check", "params": params}]}

    def test_infinity_text_is_rejected_not_coerced(self):
        with self.assertRaises(ValueError) as ctx:
            pipeline.apply_spec(self.pdir, {
                "steps": [{"type": "number_check", "params": {
                    "columns": ["temperature"]}}]})
        self.assertIn("非有限数值", str(ctx.exception))
        self.assertEqual(0, store.load_manifest(self.pdir)["latest_version"])

    def test_distinct_issue_policies_keep_originals_traceable(self):
        new_no, reports = pipeline.apply_spec(self.pdir, self.spec())
        version = store.load_version(self.pdir, new_no)
        by_id = {r["_id"]: r for r in version["rows"]}
        # nonfinite row excluded
        self.assertNotIn("r0002", by_id)
        # illegal row got the explicit replacement, not zero
        self.assertEqual(20, by_id["r0003"]["temperature"])
        # flagged rows keep their original values with review markers
        self.assertEqual("999", by_id["r0005"]["temperature"])
        self.assertIn("temperature:out_of_range", by_id["r0005"]["_review"])
        self.assertEqual("", by_id["r0004"]["temperature"])
        self.assertIn("temperature:missing", by_id["r0004"]["_review"])

        actions = reports[0]["actions"]
        by_origin = {tuple(a["origins"]): a for a in actions}
        self.assertIn("原值 'Infinity'", by_origin[("r0002",)]["description"])
        self.assertIn("排除该行", by_origin[("r0002",)]["description"])
        self.assertIn("原值 'ERR'", by_origin[("r0003",)]["description"])

    def test_replacement_must_be_explicit_finite_number(self):
        with self.assertRaises(ValueError):
            pipeline.apply_spec(self.pdir, self.spec(policies={
                "illegal": {"action": "replace", "replacement": "Infinity"}}))
        with self.assertRaises(ValueError):
            pipeline.apply_spec(self.pdir, self.spec(policies={
                "illegal": {"action": "replace"}}))

    def test_unit_convert_checks_before_and_after_conversion(self):
        csv = (
            "sample_id,t,temp_unit\n"
            "A,1e400,F\n"   # raw infinity text
            "B,1e308,F\n"   # finite raw value that overflows after scaling
            "C,10,F\n"
        )
        store.ingest_csv(self.tmp.name, "units", csv)
        udir = os.path.join(self.tmp.name, "units")
        step = {
            "type": "unit_convert", "params": {
                "column": "t", "unit_column": "temp_unit",
                "canonical_unit": "C",
                "rules": {"C": 1, "F": {
                    "factor": 0.5555555555555556,
                    "offset": -17.77777777777778}},
                "post_max_value": 1000,
                "policies": {"nonfinite": {"action": "flag"}},
                "post_policies": {"out_of_range": {"action": "drop"}},
            }}
        new_no, reports = pipeline.apply_spec(udir, {"steps": [step]})
        rows = {r["sample_id"]: r
                for r in store.load_version(udir, new_no)["rows"]}
        # pre-convert infinity kept for review with original text intact
        self.assertEqual("1e400", rows["A"]["t"])
        self.assertIn("t:nonfinite", rows["A"]["_review"])
        # post-convert overflow row excluded, referencing its original value
        self.assertNotIn("B", rows)
        post_actions = [a for a in reports[0]["actions"]
                        if a["detail"].get("stage") == "post_convert"]
        self.assertTrue(any("1e308" in a["description"]
                            and "超出有限范围" in a["description"]
                            for a in post_actions))

    def test_strategies_branch_from_same_version_without_replacing_it(self):
        # v1: exclude everything questionable
        v1_no, _ = pipeline.apply_spec(self.pdir, self.spec(), label="strict")
        self.assertEqual(1, v1_no)
        strict_rows = store.load_version(self.pdir, 1)["rows"]

        # v2 branches from v0 with a different policy; v1 must stay readable
        relaxed = self.spec(policies={
            "nonfinite": {"action": "flag"},
            "illegal": {"action": "flag"},
            "out_of_range": {"action": "flag"},
            "missing": {"action": "flag"},
        })
        v2_no, _ = pipeline.apply_spec(
            self.pdir, relaxed, label="review-all", source_version=0)
        self.assertEqual(2, v2_no)
        v2 = store.load_version(self.pdir, 2)
        self.assertEqual(0, v2["created_from"])
        self.assertEqual(5, len(v2["rows"]))
        # already-published v1 is byte-for-byte unchanged in row set/contents
        self.assertEqual(
            [(r["_id"], r.get("temperature")) for r in strict_rows],
            [(r["_id"], r.get("temperature"))
             for r in store.load_version(self.pdir, 1)["rows"]],
        )


if __name__ == "__main__":
    unittest.main()
