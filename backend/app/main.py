from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import CreateVersionRequest, DatasetRequest, PreviewRequest
from .pipeline import PipelineError, frame_from_csv, public_frame, rows_payload
from .storage import VersionStore

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
store = VersionStore(DATA_DIR)

app = FastAPI(title="实验数据清洗工作台", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "data_dir": str(DATA_DIR)}


@app.get("/api/datasets")
def list_datasets() -> dict:
    return {"datasets": store.list_datasets()}


@app.post("/api/datasets")
def create_dataset(payload: DatasetRequest) -> dict:
    try:
        frame = frame_from_csv(payload.csv_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"CSV 解析失败：{exc}") from exc
    dataset_id = uuid.uuid4().hex[:12]
    try:
        metadata = store.create_dataset(dataset_id, payload.name, frame, note="原始数据（原件不可变）")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _dataset_detail(metadata)


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> dict:
    try:
        return _dataset_detail(store.get_dataset(dataset_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/datasets/{dataset_id}/versions/{version}/rows")
def get_rows(dataset_id: str, version: str) -> dict:
    try:
        frame, resolved = store.load_frame(dataset_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"version": resolved, "columns": list(public_frame(frame).columns), "rows": rows_payload(frame)}


@app.get("/api/datasets/{dataset_id}/lineage")
def get_lineage(dataset_id: str, version: str | None = None) -> dict:
    try:
        return store.lineage(dataset_id, version)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/datasets/{dataset_id}/preview")
def preview(dataset_id: str, payload: PreviewRequest) -> dict:
    try:
        return store.preview(dataset_id, payload.base_version, payload.pipeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/datasets/{dataset_id}/versions")
def commit_version(dataset_id: str, payload: CreateVersionRequest) -> dict:
    try:
        version = store.commit(dataset_id, payload.base_version, payload.pipeline, payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"version": version, "dataset": _dataset_detail(store.get_dataset(dataset_id))}


def _dataset_detail(metadata: dict) -> dict:
    latest = metadata["versions"][-1]["version"]
    return {**metadata, "latest_version": latest}
