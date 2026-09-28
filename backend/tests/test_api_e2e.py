"""API 层端到端测试（直接调用路由函数，避免沙箱内 HTTP 栈挂起）。"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CSV = (Path(__file__).resolve().parents[1] / "sample_data.csv").read_text(encoding="utf-8")


class ApiE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        import importlib
        import app.main as main
        importlib.reload(main)
        self.main = main

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def full_pipeline(self) -> dict:
        return {
            "missing": {"strategy": "mean", "column": None, "fill_value": None},
            "unit": {
                "column": "reading", "unit_column": "unit",
                "conversions": {"bar": 100.0, "mmHg": 0.1333224,
                                 "hPa": 0.1, "psi": 6.894757},
                "target_unit": "kPa",
            },
            "merge": {"keys": ["experiment_id", "site"], "conflict": "mean"},
        }

    def test_full_flow_and_restart(self) -> None:
        from app.models import CreateVersionRequest, DatasetRequest, PreviewRequest

        created = self.main.create_dataset(DatasetRequest(name="批次A", csv_text=CSV))
        dataset_id = created["id"]
        self.assertEqual(created["latest_version"], "v1")

        bad = PreviewRequest(base_version=None, pipeline={"unit": {
            "column": "reading", "unit_column": "unit",
            "conversions": {"bar": 100.0}, "target_unit": "kPa"}})
        with self.assertRaises(HTTPException) as ctx:
            self.main.preview(dataset_id, bad)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(len(self.main.get_dataset(dataset_id)["versions"]), 1)

        preview = self.main.preview(
            dataset_id,
            PreviewRequest(base_version=None, pipeline=self.full_pipeline()),
        )
        self.assertEqual(preview["base_version"], "v1")
        self.assertEqual(preview["preview"]["rows_before"], 8)
        self.assertEqual(preview["preview"]["rows_after"], 7)
        merge_detail = next(r["detail"] for r in preview["reports"] if r["step"] == "merge")
        self.assertEqual(merge_detail["conflicting_groups"], 1)
        e003 = next(row for row in preview["preview"]["after"]
                    if row["values"]["experiment_id"] == "E-003")
        self.assertTrue(math.isclose(e003["values"]["reading"],
                                     (760 * 0.1333224 + 765 * 0.1333224) / 2,
                                     rel_tol=1e-5))
        self.assertEqual(e003["values"]["unit"], "kPa")
        self.assertEqual(e003["sources"], ["r2", "r3"])

        commit = self.main.commit_version(
            dataset_id,
            CreateVersionRequest(base_version=None, note="单位统一+合并",
                                 pipeline=self.full_pipeline()),
        )
        self.assertEqual(commit["version"]["version"], "v2")

        lineage = self.main.get_lineage(dataset_id, "v2")
        self.assertEqual(lineage["original_record_count"], 8)
        self.assertEqual(lineage["result_record_count"], 7)
        merged = [row for row in lineage["rows"] if len(row["sources"]) > 1]
        self.assertEqual(merged, [{"result_row": 3, "sources": ["r2", "r3"]}])

        v1 = self.main.get_rows(dataset_id, "v1")
        self.assertEqual(len(v1["rows"]), 8)
        self.assertIn("bar", {row["values"]["unit"] for row in v1["rows"]})

        from app.storage import VersionStore
        reopened = VersionStore(self.tmp.name).get_dataset(dataset_id)
        self.assertEqual([v["version"] for v in reopened["versions"]], ["v1", "v2"])
        self.assertEqual(reopened["versions"][1]["pipeline"]["merge"]["conflict"], "mean")

        listing = self.main.list_datasets()
        self.assertEqual([item["id"] for item in listing["datasets"]], [dataset_id])


if __name__ == "__main__":
    unittest.main()
