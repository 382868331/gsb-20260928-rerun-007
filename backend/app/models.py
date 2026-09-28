from __future__ import annotations

from pydantic import BaseModel, Field


class MissingRule(BaseModel):
    strategy: str = Field(default="mean", pattern="^(mean|median|constant|drop_row)$")
    column: str | None = None
    fill_value: float | str | None = None


class UnitRule(BaseModel):
    column: str
    unit_column: str
    conversions: dict[str, float] = Field(default_factory=dict)
    target_unit: str


class MergeRule(BaseModel):
    keys: list[str]
    conflict: str = Field(default="mean", pattern="^(mean|first|last)$")


class PipelineSpec(BaseModel):
    missing: MissingRule | None = None
    unit: UnitRule | None = None
    merge: MergeRule | None = None


class CreateVersionRequest(BaseModel):
    base_version: str | None = None
    note: str = ""
    pipeline: PipelineSpec


class PreviewRequest(BaseModel):
    base_version: str | None = None
    pipeline: PipelineSpec


class DatasetRequest(BaseModel):
    name: str
    csv_text: str
