from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .models import PipelineSpec
from .pipeline import SOURCE_COL, RunResult, frame_from_csv_file, run_pipeline


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VersionStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dataset_dir(self, dataset_id: str) -> Path:
        path = self.root / dataset_id
        if not path.exists():
            raise KeyError(f"数据集不存在：{dataset_id}")
        return path

    def _version_path(self, dataset_id: str, version: str) -> Path:
        path = self._dataset_dir(dataset_id) / f"{version}.csv"
        if not path.exists():
            raise KeyError(f"版本不存在：{version}")
        return path

    def _meta_path(self, dataset_id: str) -> Path:
        return self._dataset_dir(dataset_id) / "metadata.json"

    def list_datasets(self) -> list[dict]:
        datasets = []
        for path in sorted(self.root.iterdir()):
            if path.is_dir() and (path / "metadata.json").exists():
                datasets.append(self.get_dataset(path.name))
        return datasets

    def create_dataset(self, dataset_id: str, name: str, frame: pd.DataFrame, note: str) -> dict:
        dataset_dir = self.root / dataset_id
        if dataset_dir.exists():
            raise FileExistsError(f"数据集已存在：{dataset_id}")
        dataset_dir.mkdir(parents=True)
        self._atomic_csv(dataset_dir / "v1.csv", frame)
        metadata = {
            "id": dataset_id,
            "name": name,
            "created_at": utc_now(),
            "versions": [self._version_meta("v1", None, note, [], frame)],
        }
        self._atomic_json(self._meta_path_from(dataset_dir), metadata)
        return metadata

    def get_dataset(self, dataset_id: str) -> dict:
        with self._meta_path(dataset_id).open(encoding="utf-8") as handle:
            return json.load(handle)

    def load_frame(self, dataset_id: str, version: str | None = None) -> tuple[pd.DataFrame, str]:
        metadata = self.get_dataset(dataset_id)
        version = version or metadata["versions"][-1]["version"]
        return frame_from_csv_file(str(self._version_path(dataset_id, version))), version

    def preview(self, dataset_id: str, base_version: str | None, spec: PipelineSpec) -> dict:
        frame, resolved_base = self.load_frame(dataset_id, base_version)
        result = run_pipeline(frame, spec)
        from .pipeline import diff_preview
        return {
            "base_version": resolved_base,
            "reports": [_report_dict(report) for report in result.reports],
            "preview": diff_preview(frame, result.frame),
        }

    def commit(
        self, dataset_id: str, base_version: str | None, spec: PipelineSpec, note: str
    ) -> dict:
        metadata = self.get_dataset(dataset_id)
        frame, resolved_base = self.load_frame(dataset_id, base_version)
        result: RunResult = run_pipeline(frame, spec)

        next_number = max(int(item["version"][1:]) for item in metadata["versions"]) + 1
        next_version = f"v{next_number}"
        dataset_dir = self._dataset_dir(dataset_id)

        # 全部计算成功后才写临时文件；rename 在同目录下是原子操作，失败不会出现半份结果。
        temp_csv = dataset_dir / f".{next_version}.{os.getpid()}.tmp.csv"
        self._atomic_csv(temp_csv, result.frame)

        version_meta = self._version_meta(
            next_version, resolved_base, note,
            [_report_dict(report) for report in result.reports], result.frame, spec,
        )
        updated = {**metadata, "versions": metadata["versions"] + [version_meta]}
        temp_meta = dataset_dir / f".metadata.{os.getpid()}.tmp.json"
        self._atomic_json(temp_meta, updated)
        os.replace(temp_csv, dataset_dir / f"{next_version}.csv")
        os.replace(temp_meta, self._meta_path_from(dataset_dir))
        return version_meta

    def lineage(self, dataset_id: str, version: str | None = None) -> dict:
        metadata = self.get_dataset(dataset_id)
        resolved = version or metadata["versions"][-1]["version"]
        frame, _ = self.load_frame(dataset_id, resolved)
        rows = []
        for index, source_ids in enumerate(frame[SOURCE_COL]):
            rows.append({"result_row": index + 1, "sources": list(source_ids)})
        original_count = 0
        original = metadata["versions"][0]
        original_frame = frame_from_csv_file(str(self._dataset_dir(dataset_id) / f"{original['version']}.csv"))
        original_count = len(original_frame)
        return {
            "dataset_id": dataset_id,
            "version": resolved,
            "original_record_count": original_count,
            "result_record_count": len(frame),
            "rows": rows,
            "versions": metadata["versions"],
        }

    def _version_meta(self, version: str, parent: str | None, note: str,
                      reports: list[dict], frame: pd.DataFrame,
                      spec: PipelineSpec | None = None) -> dict:
        meta = {
            "version": version,
            "parent": parent,
            "note": note,
            "created_at": utc_now(),
            "row_count": len(frame),
            "reports": reports,
        }
        if spec is not None:
            meta["pipeline"] = json.loads(spec.model_dump_json())
        return meta

    @staticmethod
    def _meta_path_from(dataset_dir: Path) -> Path:
        return dataset_dir / "metadata.json"

    @staticmethod
    def _atomic_csv(target: Path, frame: pd.DataFrame) -> None:
        serializable = frame.copy()
        serializable[SOURCE_COL] = serializable[SOURCE_COL].apply(
            lambda ids: "|".join(ids)
        )
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                serializable.to_csv(handle, index=False)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _atomic_json(target: Path, payload: dict) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def _report_dict(report) -> dict:
    return {"step": report.step, "changed_rows": report.changed_rows, "detail": report.detail}
