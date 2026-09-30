"""Pluggable cleaning steps.

Each step is a pure function::

    apply(rows, params) -> (new_rows, lineage, stats)

- rows: list of dict records, each row carries "_id" (stable row identity).
- lineage: {new_row_id: [source_row_ids]} for every output row.
- stats: human-readable counters used by preview and reports.

Steps never mutate their input. Register new steps in STEPS and the
pipeline, preview and API pick them up automatically, so adding a step
never rebuilds existing data identities.
"""
from .missing import apply as missing_values
from .unit_convert import apply as unit_convert
from .dedup import apply as dedup_merge
from .validate_numbers import apply as validate_numbers

STEPS = {
    "missing_values": missing_values,
    "unit_convert": unit_convert,
    "dedup_merge": dedup_merge,
    "validate_numbers": validate_numbers,
}

STEP_LABELS = {
    "missing_values": "\u7f3a\u5931\u503c\u5904\u7406",
    "unit_convert": "\u5355\u4f4d\u6362\u7b97",
    "dedup_merge": "\u91cd\u590d\u8bb0\u5f55\u5408\u5e76",
    "validate_numbers": "\u6570\u503c\u6709\u6548\u6027\u68c0\u67e5",
}
