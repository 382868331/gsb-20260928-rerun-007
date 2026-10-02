"""Version comparison attributes data / rule / manual causes separately.

Includes the dropped-append case: a row arriving in a new batch that the
rules exclude is still reported as *data added* (with outcome dropped),
not silently as a rule change.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pipeline, store


CSV = (
    "sample_id,lab,temperature\n"
    "S1,lab-A,25\nS2,lab-A,ERR\nS3,lab-B,ERR\nS4,lab-B,1000\n"
)

POL = {
    "illegal": {"action": "drop"},
    "out_of_range": {"action": "drop"},
    "missing": {"action": "flag"},
    "by_source": {"lab-B": {
        "illegal": {"action": "replace", "replacement": 20},
        "out_of_range": {"action": "flag"}}},
}


def spec(policies=None):
    return {"steps": [{"type": "number_check", "params": {
        "columns": ["temperature"], "min_value": 0, "max_value": 100,
        "source_column": "lab", "policies": policies or POL}}]}


class CompareAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.pdir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_appended_dropped_row_is_data_added(self):
        from backend import compare
        v1, _ = pipeline.apply_spec(self.pdir, spec(), label="v1")
        store.append_batch(
            self.tmp.name, "lab",
            "sample_id,lab,temperature\n"
            "S5,lab-A,ERR\nS6,lab-B,22\n",
            label="batch2")
        v2, _ = pipeline.apply_spec(self.pdir, spec(), label="v2")
        result = compare.compare_versions(self.pdir, v1, v2)
        self.assertEqual([1, 2], result["data_generations"])
        self.assertEqual(["r0005", "r0006"], result["data_added_origins"])
        added = {c["origins"][0]: c["after"]
                 for c in result["attributed_changes"]["data_added"]}
        self.assertEqual("dropped", added["r0005"])
        self.assertEqual("present", added["r0006"])
        self.assertEqual([], result["attributed_changes"]["rule_changed"])

    def test_rule_only_change_without_new_data(self):
        from backend import compare
        v1, _ = pipeline.apply_spec(self.pdir, spec(), label="v1")
        changed = {"illegal": {"action": "flag"},
                   "out_of_range": {"action": "drop"},
                   "missing": {"action": "flag"},
                   "by_source": POL["by_source"]}
        v2, _ = pipeline.apply_spec(self.pdir, spec(changed), label="v2")
        result = compare.compare_versions(self.pdir, v1, v2)
        self.assertTrue(result["rules_changed"])
        self.assertEqual([], result["data_added_origins"])
        rule_origins = {tuple(c["origins"]) for c in
                        result["attributed_changes"]["rule_changed"]}
        self.assertIn(("r0002",), rule_origins)


if __name__ == "__main__":
    unittest.main()
