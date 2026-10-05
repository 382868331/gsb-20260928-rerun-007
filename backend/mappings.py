"""Explicit measurement mappings for evolved batch schemas."""

UNIT_TOKENS = {"unit", "units", "uom", "单位"}
VALUE_TOKENS = {"value", "values", "num", "number", "numeric", "数值", "数字"}


def clean(name):
    return str(name or "").strip().lower().replace("-", "_")


def mapping_id(batch_no, target_column, source_column=None, sources=None):
    suffix = f":{source_column}" if source_column else ""
    if source_column and sources:
        suffix += "=" + ",".join(sorted(str(s) for s in sources))
    return f"b{batch_no}:{target_column}{suffix}"


def rows_for_batch(raw_rows, batch_no):
    return [row for row in raw_rows if row.get("_batch") == batch_no]


def is_unit_column(column, target):
    text, base = clean(column), clean(target)
    if text in UNIT_TOKENS or text in {base + "_unit", base + "_uom",
                                       clean(target) + "unit"}:
        return True
    return any(text.endswith("_" + token) for token in UNIT_TOKENS)


def value_candidates(target, columns):
    base = clean(target)
    exact, named, suffixed = [], [], []
    for column in columns:
        text = clean(column)
        if text == base:
            exact.append(column)
        elif is_unit_column(column, target):
            continue
        elif text.startswith(base):
            tail = text[len(base):].lstrip("_")
            (named if tail in VALUE_TOKENS else suffixed).append(column)
    candidates = exact + named + suffixed
    return exact, candidates


def unit_candidates(target, columns, configured=None):
    found = []
    if configured and configured in columns:
        found.append(configured)
    for column in columns:
        if column not in found and is_unit_column(column, target):
            found.append(column)
    return found


def rule_targets(steps):
    targets = {}
    for index, step in enumerate(steps or []):
        kind = step.get("type")
        params = step.get("params") or {}
        if kind in ("number_check", "missing_values"):
            cols = list(params.get("columns") or [])
            cols.extend(key for key in (params.get("policies") or {})
                        if key not in cols)
            for column in cols:
                targets.setdefault(column, []).append(
                    {"step_index": index, "step_type": kind})
        if kind == "unit_convert" and params.get("column"):
            targets.setdefault(params["column"], []).append({
                "step_index": index, "step_type": kind,
                "unit_column": params.get("unit_column"),
                "canonical_unit": params.get("canonical_unit")})
    return targets


def source_scoped_rules(steps, target):
    columns = set()
    for step in steps or []:
        rules = (step.get("params", {}).get("policies", {})
                 .get(target, []))
        if isinstance(rules, dict):
            rules = rules.get("rules", [])
        for rule in rules if isinstance(rules, list) else []:
            if isinstance(rule, dict) and (rule.get("source_column")
                                           or rule.get("sources")):
                if rule.get("source_column"):
                    columns.add(rule["source_column"])
    return columns


def analyze_schema(old_columns, new_columns, rows, batch_no=None, steps=None):
    targets = rule_targets(steps)
    target_columns = list(targets) or [c for c in old_columns
                                       if c not in set(new_columns)]
    proposals = []
    for target in target_columns:
        exact, values = value_candidates(target, new_columns)
        configured_units = [r.get("unit_column") for refs
                            in targets.get(target, []) for r in [refs]
                            if r.get("unit_column")]
        units = unit_candidates(target, new_columns,
                                configured_units[0] if configured_units else None)
        scoped_columns = source_scoped_rules(steps, target)
        scoped = bool(scoped_columns)
        source_reusable = all(column in new_columns for column in scoped_columns)
        configured_unit = configured_units[0] if configured_units else None
        configured_missing = bool(configured_unit) and configured_unit not in new_columns
        direct_reusable = target in new_columns and not configured_missing and (
            not units or (configured_unit and configured_unit in units))
        if direct_reusable and (not scoped or source_reusable):
            status, inheritance = "reusable", "reusable"
            values, confirmed = [target], True
            reason = "新旧列完全同名，可沿用原规则。"
        elif len(values) > 1:
            status, inheritance, confirmed = "ambiguous", "needs_mapping", False
            reason = "存在多个可能的新测量列，需人工确认，不能按列名自动选择。"
        elif values:
            status, inheritance, confirmed = "needs_mapping", "needs_mapping", False
            reason = "数值/单位结构变化，需要确认测量对应关系。"
            if scoped:
                reason += " 旧规则还按来源区分测量对象，必须逐来源确认。"
        else:
            status, inheritance, confirmed = "missing", "conflicting", False
            reason = "未找到可对应的新测量列，旧规则无法采用。"
        if configured_missing and status == "reusable":
            status, inheritance, confirmed = "needs_mapping", "needs_mapping", False
            reason = f"单位列 {configured_unit} 缺失或改为逐条记录，需要确认新的单位解释。"
        elif configured_missing:
            status = inheritance = "needs_mapping" if values else "conflicting"
            inheritance = status
            confirmed = False
            reason += f" 旧规则依赖单位列 {configured_unit}，还需确认单位解释。"
        sample_units = sorted({str(row.get(units[0]) or "").strip()
                               for row in rows if units})[:10] if units else []
        proposals.append({
            "id": mapping_id(batch_no, target),
            "batch": batch_no,
            "target_column": target,
            "status": status,
            "confirmed": confirmed,
            "rule_inheritance": inheritance,
            "candidate_columns": values,
            "value_columns": values if len(values) == 1 else [],
            "unit_candidates": units,
            "unit_column": units[0] if len(units) == 1 else None,
            "unit_mode": "per_row" if units else "fixed_default",
            "sample_units": sample_units,
            "default_unit": None,
            "source_column": None,
            "sources": [],
            "rules": targets.get(target, []),
            "reason": reason,
        })
    return {
        "old_columns": list(old_columns), "new_columns": list(new_columns),
        "added_columns": [c for c in new_columns if c not in set(old_columns)],
        "removed_columns": [c for c in old_columns if c not in set(new_columns)],
        "mappings": proposals,
        "summary": {
            "reusable": sum(p["rule_inheritance"] == "reusable" for p in proposals),
            "needs_mapping": sum(p["rule_inheritance"] == "needs_mapping" for p in proposals),
            "conflicting": sum(p["rule_inheritance"] == "conflicting" for p in proposals)},
    }


def normalize_mapping(batch_no, item):
    if not isinstance(item, dict):
        raise ValueError("mapping must be an object")
    target = item.get("target_column")
    if not target:
        raise ValueError("mapping needs target_column")
    values = item.get("value_columns") or item.get("candidate_columns") or []
    if isinstance(values, str):
        values = [values]
    if not values and item.get("value_column"):
        values = [item["value_column"]]
    if len(values) != 1:
        raise ValueError("请明确选择一个新测量数值列；多个测量请分别确认")
    sources = item.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    if sources and not item.get("source_column"):
        raise ValueError("按来源确认测量时必须提供 source_column")
    source_column = item.get("source_column") or None
    default_unit = item.get("default_unit")
    default_unit = str(default_unit).strip() if default_unit is not None else None
    default_unit = default_unit or None
    return {
        "id": item.get("id") or mapping_id(batch_no, target, source_column,
                                           sources),
        "batch": batch_no,
        "target_column": target,
        "measurement": item.get("measurement") or target,
        "value_column": values[0],
        "value_columns": list(values),
        "unit_column": item.get("unit_column") or None,
        "unit_mode": "per_row" if item.get("unit_column") else "fixed_default",
        "default_unit": default_unit,
        "source_column": source_column,
        "sources": list(sources),
        "status": "confirmed",
        "confirmed": True,
        "raw_format": item.get("raw_format",
                               "split_value_unit" if item.get("unit_column") else "direct"),
        "description": item.get("description", ""),
    }


def implicit_reusable_mappings(old_columns, appended_meta, raw_rows, steps):
    result = []
    for batch_no in sorted({item.get("batch") for item in appended_meta}):
        meta = next(item for item in appended_meta if item.get("batch") == batch_no)
        columns = meta.get("columns") or []
        rows = [row for row in raw_rows if row.get("_batch") == batch_no]
        analysis_result = analyze_schema(old_columns, columns, rows,
                                         batch_no=batch_no, steps=steps)
        for proposal in analysis_result["mappings"]:
            if proposal["rule_inheritance"] != "reusable":
                continue
            mapping = normalize_mapping(batch_no, {
                "target_column": proposal["target_column"],
                "value_column": proposal["target_column"],
                "unit_column": proposal.get("unit_column"),
                "default_unit": next((r.get("canonical_unit") for r in proposal["rules"]
                                      if r.get("canonical_unit")), None),
            })
            mapping["id"] = mapping_id(batch_no, proposal["target_column"], "auto")
            mapping["implicit"] = True
            result.append(mapping)
    return result


def matches(row, mapping):
    if not mapping.get("source_column") or not mapping.get("sources"):
        return True
    return str(row.get(mapping["source_column"]) or "").strip() in {
        str(value) for value in mapping["sources"]}


def resolve_unit(raw, mapping):
    """Pick the effective unit for one raw row under a confirmed mapping.

    Returns (unit, unit_source) where unit_source is one of:
    "per_row"  - an explicitly filled per-row unit cell;
    "default"  - the cell was blank and the batch-level default applied;
    "missing"  - neither a filled cell nor a default exists.
    Blank, unknown and explicit units stay distinguishable downstream.
    """
    raw_unit = (raw.get(mapping["unit_column"])
                if mapping.get("unit_column") else None)
    if raw_unit is not None and str(raw_unit).strip():
        return str(raw_unit).strip(), "per_row"
    if mapping.get("default_unit"):
        return str(mapping["default_unit"]).strip(), "default"
    if mapping.get("unit_column"):
        return "", "missing"
    return None, "missing"


def apply_mappings(raw_rows, appended_meta, mappings, old_columns,
                   required_targets=None, legacy_unit_columns=None):
    """Project raw appended rows into the legacy measurement schema."""
    appended_ids = {item["_id"]: item for item in appended_meta}
    original_rows = [row for row in raw_rows if row.get("_id") not in appended_ids]
    confirmed = [m for m in mappings if m.get("confirmed")
                 and m.get("status") == "confirmed"]
    adapted = [dict(row) for row in original_rows]
    pending, traces = [], {}
    for raw in raw_rows:
        meta = appended_ids.get(raw.get("_id"))
        if not meta:
            continue
        batch_no = meta.get("batch")
        selected = [m for m in confirmed if m.get("batch") == batch_no
                    and matches(raw, m)]
        targets = [m["target_column"] for m in selected]
        required = set(required_targets or [])
        if not selected or (required and not required.issubset(set(targets))):
            status = "partial" if selected else "pending"
            pending.append(dict(raw, _mapping_status=status,
                                _confirmed_mapping_ids=[m["id"] for m in selected],
                                _missing_targets=sorted(required - set(targets))))
            continue
        if len(targets) != len(set(targets)):
            raise ValueError(f"{raw['_id']} 的同一测量存在矛盾对应")
        projected = {key: value for key, value in raw.items()
                     if not key.startswith("_")}
        for key in old_columns:
            projected.setdefault(key, raw.get(key, ""))
        projected.update({"_id": raw["_id"], "_batch": batch_no,
                          "_mapping_status": "confirmed",
                          "_mapping_ids": [m["id"] for m in selected]})
        row_trace = []
        for mapping in selected:
            target = mapping["target_column"]
            value = raw.get(mapping["value_column"], "")
            unit, unit_source = resolve_unit(raw, mapping)
            legacy_unit_column = (legacy_unit_columns or {}).get(target)
            projected[target] = value
            if mapping.get("unit_column"):
                projected[mapping["unit_column"]] = (
                    raw.get(mapping["unit_column"], ""))
            if legacy_unit_column:
                # Old cleaning rules still read the legacy unit column;
                # the confirmed interpretation must reach them even when
                # both the value and the unit column were renamed.
                projected[legacy_unit_column] = (
                    unit if unit is not None else "")
            projected[f"_raw_{target}"] = value
            projected[f"_raw_{target}_unit"] = unit
            projected[f"_raw_{target}_unit_source"] = unit_source
            projected[f"_raw_{target}_column"] = mapping["value_column"]
            row_trace.append({
                "row_id": raw["_id"], "target_column": target,
                "source_value_column": mapping["value_column"],
                "original_text": value,
                "source_unit_column": mapping.get("unit_column"),
                "original_unit": unit, "unit_source": unit_source,
                "unit_mode": mapping["unit_mode"],
                "legacy_unit_column": legacy_unit_column,
                "mapping_id": mapping["id"],
                "explanation": (
                    f"结构对应：{mapping['value_column']} → {target}"
                    + _unit_explanation(mapping, unit, unit_source)
                    + (f"（写入旧单位列 {legacy_unit_column}）"
                       if legacy_unit_column else ""))})
        adapted.append(projected)
        traces[raw["_id"]] = row_trace
    return adapted, pending, traces


def _unit_explanation(mapping, unit, unit_source):
    if not mapping.get("unit_column"):
        return f"；固定单位 {unit}" if unit is not None else ""
    column = mapping["unit_column"]
    if unit_source == "per_row":
        return f"；逐行单位列 {column} 显式单位：{unit}"
    if unit_source == "default":
        return (f"；逐行单位列 {column} 该行为空，"
                f"采用整列默认单位：{unit}")
    return f"；逐行单位列 {column} 该行为空且未配置整列默认单位"


def mapping_trace_report(traces):
    return [{"origins": [row_id], "description": item["explanation"],
             "detail": item}
            for row_id, items in traces.items() for item in items]
