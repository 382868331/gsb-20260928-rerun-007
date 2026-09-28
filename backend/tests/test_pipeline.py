from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import (
    MergeRule, MissingRule, PipelineSpec, UnitRule,
)
from app.pipeline import PipelineError, frame_from_csv, run_pipeline
from app.storage import VersionStore

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data.csv"

READING_TO_KPA = {
    "bar": 100.0, "mmHg": 0.1333224, "hPa": 0.1, "psi": 6.894757,
}
TEMP_TO_C = {"K": 1.0}


def full_spec() -> PipelineSpec:
    return PipelineSpec(
        missing=MissingRule(strategy="mean"),
        unit=UnitRule(column="reading", unit_column="unit",
                      conversions=READING_TO_KPA, target_unit="kPa"),
        merge=MergeRule(keys=["experiment_id", "site"], conflict="mean"),
    )


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = frame_from_csv(SAMPLE.read_text(encoding="utf-8"))

    def test_unit_conflict_and_merge_lineage(self) -> None:
        spec = full_spec()
        # 先换算温度：K -> C（298.15K = 25C），这里只对 reading 做演示主链路
        result = run_pipeline(self.frame, spec)
        merged_e003 = result.frame[result.frame["experiment_id"] == "E-003"].iloc[0]
        expected = (760.0 * 0.1333224 + 765.0 * 0.1333224) / 2
        self.assertAlmostEqual(merged_e003["reading"], expected, places=6)
        self.assertEqual(set(merged_e003["__source_ids__"]), {"r2", "r3"})
        self.assertTrue((result.frame["unit"] == "kPa").all())
        merge_report = next(item for item in result.reports if item.step == "merge")
        self.assertEqual(merge_report.detail["conflicting_groups"], 1)
        self.assertEqual(merge_report.detail["rows_removed"], 1)
        missing_report = next(item for item in result.reports if item.step == "missing")
        self.assertGreater(missing_report.detail["filled_cells"], 0)

    def test_unknown_unit_aborts_without_partial_result(self) -> None:
        spec = PipelineSpec(unit=UnitRule(
            column="reading", unit_column="unit",
            conversions={"bar": 100.0}, target_unit="kPa"))
        with self.assertRaises(PipelineError):
            run_pipeline(self.frame, spec)

    def test_drop_row_then_merge(self) -> None:
        spec = PipelineSpec(
            missing=MissingRule(strategy="drop_row"),
            unit=UnitRule(column="reading", unit_column="unit",
                          conversions=READING_TO_KPA, target_unit="kPa"),
            merge=MergeRule(keys=["experiment_id"], conflict="last"),
        )
        result = run_pipeline(self.frame, spec)
        # E-002/E-004/E-005 存在缺失被丢弃（8→5），E-003 再合并为 1 行（5→4）
        self.assertEqual(len(result.frame), 4)


class StorageTests(unittest.TestCase):
    def test_failed_commit_publishes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = VersionStore(tmp)
            frame = frame_from_csv(SAMPLE.read_text(encoding="utf-8"))
            store.create_dataset("ds1", "样例", frame, "原件")
            bad_spec = PipelineSpec(unit=UnitRule(
                column="reading", unit_column="unit",
                conversions={"bar": 100.0}, target_unit="kPa"))
            with self.assertRaises(PipelineError):
                store.commit("ds1", None, bad_spec, "坏规则")
            metadata = store.get_dataset("ds1")
            self.assertEqual([item["version"] for item in metadata["versions"]], ["v1"])
            leftovers = [p.name for p in Path(tmp, "ds1").iterdir() if "tmp" in p.name]
            self.assertEqual(leftovers, [])

            good_spec = PipelineSpec(
                missing=MissingRule(strategy="mean"),
                unit=UnitRule(column="reading", unit_column="unit",
                              conversions=READING_TO_KPA, target_unit="kPa"),
                merge=MergeRule(keys=["experiment_id"], conflict="mean"),
            )
            store.commit("ds1", None, good_spec, "换算并合并")
            lineage = store.lineage("ds1")
            self.assertEqual(lineage["original_record_count"], 8)
            self.assertEqual(lineage["result_record_count"], 7)
            e003 = next(row for row in lineage["rows"]
                        if len(row["sources"]) == 2)
            self.assertEqual(e003["sources"], ["r2", "r3"])
            reopened = VersionStore(tmp).get_dataset("ds1")
            self.assertEqual(len(reopened["versions"]), 2)


if __name__ == "__main__":
    unittest.main()
