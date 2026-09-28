from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .models import MergeRule, MissingRule, PipelineSpec, UnitRule

SOURCE_COL = "__source_ids__"


class PipelineError(ValueError):
    """流水线配置或数据错误：调用方不得发布任何结果。"""


@dataclass
class StepReport:
    step: str
    changed_rows: int
    detail: dict


@dataclass
class RunResult:
    frame: pd.DataFrame
    reports: list[StepReport]


def frame_from_csv(csv_text: str) -> pd.DataFrame:
    frame = pd.read_csv(pd.io.common.StringIO(csv_text))
    frame.columns = [str(c) for c in frame.columns]
    if frame.empty:
        raise PipelineError("数据为空，至少需要一行记录")
    frame[SOURCE_COL] = [[f"r{i}"] for i in range(len(frame))]
    return frame


def frame_from_csv_file(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if SOURCE_COL not in frame.columns:
        raise PipelineError(f"版本文件缺少血缘列 {SOURCE_COL}")
    frame[SOURCE_COL] = frame[SOURCE_COL].apply(_parse_id_list)
    return frame


def _parse_id_list(value: object) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, float) and math.isnan(value):
        return []
    text = str(value)
    if "|" in text:
        return [part.strip() for part in text.split("|") if part.strip()]
    text = text.strip("[]")
    return [part.strip().strip(chr(39) + chr(34)) for part in text.split(",") if part.strip()]


def public_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(columns=[SOURCE_COL])


def rows_payload(frame: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    for record in frame.to_dict(orient="records"):
        source_ids = record.pop(SOURCE_COL)
        rows.append({"sources": list(source_ids), "values": _jsonable(record)})
    return rows


def _jsonable(record: dict) -> dict:
    clean = {}
    for key, value in record.items():
        if value is None or (isinstance(value, float) and math.isnan(value)):
            clean[key] = None
        elif hasattr(value, "item"):
            clean[key] = value.item()
        else:
            clean[key] = value
    return clean


def run_pipeline(frame: pd.DataFrame, spec: PipelineSpec) -> RunResult:
    reports: list[StepReport] = []
    current = frame.copy()
    if spec.missing is not None:
        current, report = _apply_missing(current, spec.missing)
        reports.append(report)
    if spec.unit is not None:
        current, report = _apply_unit(current, spec.unit)
        reports.append(report)
    if spec.merge is not None:
        current, report = _apply_merge(current, spec.merge)
        reports.append(report)
    if not reports:
        raise PipelineError("流水线至少需要一个处理步骤")
    return RunResult(frame=current.reset_index(drop=True), reports=reports)


def _require_columns(frame: pd.DataFrame, columns: list[str], step: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise PipelineError(f"{step} 步骤引用了不存在的列：{', '.join(missing)}")


def _apply_missing(frame: pd.DataFrame, rule: MissingRule) -> tuple[pd.DataFrame, StepReport]:
    before = public_frame(frame).copy()
    columns = [rule.column] if rule.column else frame.select_dtypes(include="number").columns.tolist()
    _require_columns(frame, columns, "缺失值处理")

    if rule.strategy == "drop_row":
        target = columns if rule.column else frame.columns.drop(SOURCE_COL).tolist()
        keep = ~frame[target].isna().any(axis=1)
        dropped = int((~keep).sum())
        return frame[keep].reset_index(drop=True), StepReport(
            "missing", dropped, {"strategy": "drop_row", "dropped_rows": dropped, "columns": target}
        )

    if rule.strategy == "constant":
        if rule.fill_value is None:
            raise PipelineError("constant 策略必须提供 fill_value")
        fills = {column: rule.fill_value for column in columns}
    else:
        numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().all().any():
            raise PipelineError("均值/中位数只能用于存在数值的列")
        stat = numeric.mean(numeric_only=False) if rule.strategy == "mean" else numeric.median(numeric_only=False)
        fills = {column: stat[column] for column in columns}
        frame[columns] = numeric

    filled_total = 0
    per_column: dict[str, int] = {}
    for column, fill in fills.items():
        count = int(frame[column].isna().sum())
        per_column[column] = count
        filled_total += count
        frame[column] = frame[column].fillna(fill)

    changed = int((before.fillna("<<NA>>") != public_frame(frame).fillna("<<NA>>")).any(axis=1).sum())
    return frame, StepReport(
        "missing", changed,
        {"strategy": rule.strategy, "filled_cells": filled_total, "per_column": per_column},
    )


def _apply_unit(frame: pd.DataFrame, rule: UnitRule) -> tuple[pd.DataFrame, StepReport]:
    _require_columns(frame, [rule.column, rule.unit_column], "单位换算")
    if not rule.conversions:
        raise PipelineError("单位换算必须提供至少一组换算系数")

    units = frame[rule.unit_column].astype("string")
    known = set(rule.conversions) | {rule.target_unit}
    unknown = sorted(set(units.dropna()) - known)
    if unknown:
        raise PipelineError(f"存在未声明换算系数的单位：{', '.join(unknown)}")

    values = pd.to_numeric(frame[rule.column], errors="coerce")
    if values.isna().any():
        raise PipelineError(f"列 {rule.column} 存在缺失或非数值，请先处理缺失值")

    factors = units.map(lambda unit: 1.0 if unit == rule.target_unit else float(rule.conversions[unit]))
    converted = values * factors
    changed_mask = (converted.round(10) != values.round(10)) | (units != rule.target_unit)
    frame[rule.column] = converted
    frame[rule.unit_column] = rule.target_unit
    changed_rows = int(changed_mask.sum())
    return frame, StepReport(
        "unit", changed_rows,
        {"column": rule.column, "target_unit": rule.target_unit,
         "conversions": rule.conversions, "changed_rows": changed_rows},
    )


def _apply_merge(frame: pd.DataFrame, rule: MergeRule) -> tuple[pd.DataFrame, StepReport]:
    _require_columns(frame, rule.keys, "重复记录合并")
    if not rule.keys:
        raise PipelineError("合并必须指定至少一个键列")

    value_columns = [column for column in frame.columns if column not in rule.keys + [SOURCE_COL]]
    numeric_columns = frame[value_columns].select_dtypes(include="number").columns.tolist()
    group_sizes = frame.groupby(rule.keys, dropna=False).size()
    duplicate_keys = group_sizes[group_sizes > 1]

    conflicting_groups = 0
    merged_rows: list[pd.Series] = []
    for key_values, group in frame.groupby(rule.keys, dropna=False, sort=False):
        if len(group) == 1:
            merged_rows.append(group.iloc[0])
            continue
        numeric_conflict = any(
            group[column].nunique(dropna=False) > 1 for column in numeric_columns
        )
        non_numeric = [column for column in value_columns if column not in numeric_columns]
        text_conflict = any(group[column].nunique(dropna=False) > 1 for column in non_numeric)
        if numeric_conflict or text_conflict:
            conflicting_groups += 1

        record = {SOURCE_COL: sorted({item for ids in group[SOURCE_COL] for item in ids})}
        key_values = key_values if isinstance(key_values, tuple) else (key_values,)
        for key, value in zip(rule.keys, key_values):
            record[key] = value
        for column in value_columns:
            if column in numeric_columns:
                series = pd.to_numeric(group[column], errors="coerce")
                record[column] = {
                    "mean": series.mean(), "first": group[column].iloc[0],
                    "last": group[column].iloc[-1],
                }[rule.conflict]
            else:
                record[column] = group[column].iloc[0]
        merged_rows.append(pd.Series(record))

    merged = pd.DataFrame(merged_rows).reset_index(drop=True)
    return merged, StepReport(
        "merge", int(len(duplicate_keys)),
        {"keys": rule.keys, "conflict": rule.conflict,
         "duplicate_groups": int(len(duplicate_keys)),
         "rows_removed": int(len(frame) - len(merged)),
         "conflicting_groups": conflicting_groups},
    )
def diff_preview(base: pd.DataFrame, result: pd.DataFrame) -> dict:
    return {
        "rows_before": len(base),
        "rows_after": len(result),
        "before": rows_payload(base.head(8)),
        "after": rows_payload(result.head(8)),
    }
