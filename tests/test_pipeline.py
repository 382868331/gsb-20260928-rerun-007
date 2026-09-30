import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import pipeline, store


CSV = (
    "sample_id,temperature,temp_unit,pressure\n"
    "S1,25.0,C,101.3\n"
    "S2,77.0,F,101.1\n"
    "S3,30.0,C,\n"
    "S1,25.0,C,101.3\n"       # exact duplicate of row 1
    "S2,25.0,C,101.1\n"       # same sample, unit-normalised duplicate
    "S4,,C,99.8\n"            # missing temperature
    "S5,212.0,F,100.5\n"
)

SPEC = {
    "steps": [
        {"type": "unit_convert", "params": {
            "column": "temperature", "unit_column": "temp_unit",
            "canonical_unit": "C", "rules": {
                "C": 1.0,
                "F": {"factor": 0.5555555555555556,
                      "offset": -17.77777777777778}}}},
        {"type": "missing_values", "params": {
            "columns": ["pressure"], "strategy": "fill_mean"}},
        {"type": "missing_values", "params": {
            "columns": ["temperature"], "strategy": "fill_median"}},
        {"type": "dedup_merge", "params": {
            "keys": ["sample_id"], "merge": "mean",
            "on_conflict": "keep_all"}},
    ]
}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store.ingest_csv(self.tmp.name, "lab", CSV)
        self.project_dir = os.path.join(self.tmp.name, "lab")

    def tearDown(self):
        self.tmp.cleanup()

    def test_mixed_units_then_duplicate_merge(self):
        new_no, reports = pipeline.apply_spec(self.project_dir, SPEC, label="run1")
        self.assertEqual(new_no, 1)
        version = store.load_version(self.project_dir, 1)
        rows = {r["sample_id"]: r for r in version["rows"]}
        # 77F and 212F converted: 25C and 100C
        self.assertAlmostEqual(rows["S2"]["temperature"], 25.0, places=4)
        self.assertAlmostEqual(rows["S5"]["temperature"], 100.0, places=4)
        self.assertEqual(5, len(rows))  # S1, S2 merged with their dupes
        # dedup report records the conflict on temperature for S2?
        # S2 values agree (25, 25) so no conflict; S1 exact dup -> none.
        dedup_stats = reports[-1]["stats"]
        self.assertEqual(2, dedup_stats["duplicate_groups"])
        self.assertEqual(2, dedup_stats["rows_removed"])

    def test_lineage_traces_to_original_records(self):
        pipeline.apply_spec(self.project_dir, SPEC)
        version = store.load_version(self.project_dir, 1)
        rows = {r["sample_id"]: r for r in version["rows"]}
        merged_id = rows["S1"]["_id"]
        origins = version["lineage"][merged_id]
        # S1 came from original r0001 and r0004
        self.assertEqual(["r0001", "r0004"], origins)
        origins_s2 = version["lineage"][rows["S2"]["_id"]]
        self.assertEqual(["r0002", "r0005"], origins_s2)

    def test_failed_step_publishes_nothing(self):
        before = store.load_manifest(self.project_dir)["latest_version"]
        bad = {"steps": [
            {"type": "unit_convert", "params": {
                "column": "temperature", "unit_column": "temp_unit",
                "canonical_unit": "C", "rules": {"C": 1.0}}}  # F missing
        ]}
        with self.assertRaises(ValueError):
            pipeline.apply_spec(self.project_dir, bad)
        after = store.load_manifest(self.project_dir)
        self.assertEqual(before, after["latest_version"])
        self.assertFalse(os.path.exists(
            os.path.join(self.project_dir, "versions", "v1.json")))

    def test_conflicting_duplicates_abort_with_error_policy(self):
        csv2 = "sample_id,temp\nA,10\nA,20\n"
        store.ingest_csv(self.tmp.name, "conflict", csv2)
        pdir = os.path.join(self.tmp.name, "conflict")
        spec = {"steps": [{"type": "dedup_merge", "params": {
            "keys": ["sample_id"], "merge": "mean",
            "on_conflict": "error"}}]}
        # mean resolves numeric conflict, so error policy only fires when
        # values truly cannot merge -> use first strategy with error instead
        spec["steps"][0]["params"]["merge"] = "first"
        with self.assertRaises(ValueError):
            pipeline.apply_spec(pdir, spec)
        self.assertEqual(0, store.load_manifest(pdir)["latest_version"])

    def test_reopen_shows_versions(self):
        pipeline.apply_spec(self.project_dir, SPEC)
        manifest = store.load_manifest(self.project_dir)
        self.assertEqual([0, 1], [v["version"] for v in manifest["versions"]])
        self.assertEqual(1, manifest["latest_version"])
        v0 = store.load_version(self.project_dir, 0)
        self.assertEqual(7, len(v0["rows"]))  # originals untouched

    def test_illegal_number_aborts_and_publishes_nothing(self):
        bad_csv = CSV + "S6,oops,F,100.1\n"
        store.ingest_csv(self.tmp.name, "illegal", bad_csv)
        pdir = os.path.join(self.tmp.name, "illegal")
        unit_step = SPEC["steps"][0]
        with self.assertRaises(ValueError) as ctx:
            pipeline.apply_spec(pdir, {"steps": [unit_step]})
        self.assertIn("non-numeric", str(ctx.exception))
        self.assertEqual(0, store.load_manifest(pdir)["latest_version"])

    def test_lineage_carries_applied_actions(self):
        pipeline.apply_spec(self.project_dir, SPEC)
        version = store.load_version(self.project_dir, 1)
        rows = {r["sample_id"]: r for r in version["rows"]}
        s2 = rows["S2"]
        descriptions = []
        for step in version["step_actions"]:
            for action in step["actions"]:
                if s2["_id"] in action["origins"]:
                    descriptions.append(action["description"])
        joined = " | ".join(descriptions)
        self.assertIn("单位换算", joined)
        self.assertIn("重复合并", joined)


if __name__ == "__main__":
    unittest.main()
