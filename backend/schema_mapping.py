"""Explicit measurement correspondence for structurally changed batches."""
import copy
import csv
import io

UNIT_SUFFIXES = ("_unit", "_units", "unit", "units")
VALUE_SUFFIXES = ("_value", "_values", "_num", "_number", "value", "values")


def parse_csv(csv_text):
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    columns = [c.strip() for c in reader.fieldnames if c is not None]
    rows = []
    for record in reader:
        rows.append({k: ("" if record.get(k) is None else record.get(k, ""))
                     for k in columns})
    if not rows:
        raise ValueError("CSV contains no data rows")
    return columns, rows


def _base_name(column):
    lowered = column.lower()
    for suffix in UNIT_SUFFIXES + VALUE_SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix):
            return column[:-len(suffix)].rstrip("_-. ")
    return column


def rule_measurement_columns(steps):
    columns = set()
    for step in steps or []:
        params = step.get("params", {}) if isinstance(step, dict) else {}
        if params.get("column"):
            columns.add(str(params["column"]))
        for key in ("columns", "numeric_columns"):
            columns.update(str(c) for c in params.get(key) or [])
        policies = params.get("policies") or {}
        if isinstance(policies, dict):
            columns.update(str(k) for k in policies
                           if not str(k).startswith("_"))
    return columns


def _unit_partner(value_col, columns):
    base = _base_name(value_col)
    for candidate in (base + "_unit", base + "Unit", base + "_units"):
        if candidate in columns:
            return candidate
    lowered = base.lower()
    for col in columns:
        if col != value_col and _base_name(col).lower() == lowered and (
                col.lower().endswith("unit") or col.lower().endswith("units")):
            return col
    return None


def build_proposal(old_columns, new_columns, new_rows, steps=None, batch=None,
                   candidates=None):
    """Suggest, but never choose, structural measurement correspondences."""
    old_set = set(old_columns)
    ruled = rule_measurement_columns(steps)
    available = [c for c in (candidates or old_columns) if c in old_set]
    consumed = set()
    measurements = []

    for col in new_columns:
        if col in consumed:
            continue
        unit_partner = _unit_partner(col, new_columns)
        is_standalone_unit = (col.lower().endswith("unit") or
                              col.lower().endswith("units")) and not unit_partner
        if is_standalone_unit:
            continue
        source_columns = [col]
        unit_columns = []
        representation = "direct"
        if unit_partner:
            source_columns.append(unit_partner)
            unit_columns.append(unit_partner)
            consumed.add(unit_partner)
            representation = "value_with_per_row_unit"

        matches = []
        base = _base_name(col)
        if col in old_set:
            matches.append(col)
        if base != col and base in old_set and base not in matches:
            matches.append(base)
        explicit = (candidates or {}).get(col)
        if explicit:
            explicit_list = explicit if isinstance(explicit, list) else [explicit]
            matches = [m for m in explicit_list if m in old_set]
        if not matches and len(available) == 1:
            matches = list(available)

        target = matches[0] if len(matches) == 1 else None
        if len(matches) > 1:
            status = "ambiguous"
        elif target:
            status = "suggested"
        elif len(available) > 1:
            status = "ambiguous"
        else:
            status = "new_measurement"

        if target in ruled:
            rule_status = "needs_unit_correspondence" if unit_columns else "reusable_after_confirmation"
        elif target:
            rule_status = "no_existing_rule"
            if col == target and not unit_columns:
                status = "inherited"
        else:
            rule_status = "needs_correspondence"

        measurements.append({
            "id": f"batch-{batch}-m{len(measurements) + 1}" if batch else f"m{len(measurements) + 1}",
            "batch": batch,
            "source_columns": source_columns,
            "value_column": col,
            "unit_columns": unit_columns,
            "representation": representation,
            "candidate_measurements": matches or available,
            "target_measurement": target,
            "target_unit_column": "temp_unit" if unit_columns and "temp_unit" in old_set else None,
            "fixed_unit": None,
            "status": status,
            "rule_status": rule_status,
            "sample_values": [
                {c: row.get(c, "") for c in source_columns}
                for row in new_rows[:3]],
            "row_ids": [row.get("_id") for row in new_rows if row.get("_id")],
        })

    reusable = [m["id"] for m in measurements
                if m["rule_status"] == "reusable_after_confirmation"]
    needing = [m["id"] for m in measurements
               if m["rule_status"] in ("needs_correspondence",
                                       "needs_unit_correspondence")]
    conflicts = [m["id"] for m in measurements if m["status"] == "ambiguous"]
    return {
        "batch": batch,
        "old_columns": old_columns,
        "new_columns": new_columns,
        "status": "pending" if conflicts or any(m["target_measurement"] is None for m in measurements) else "ready_to_confirm",
        "measurements": measurements,
        "rule_classification": {
            "reusable": reusable,
            "needs_correspondence": needing,
            "conflicting": conflicts,
        },
    }


def confirmed_map(proposal, confirmed):
    by_id = {m["id"]: m for m in proposal.get("measurements", [])}
    result = {}
    for item in confirmed or []:
        mapping_id = item.get("id") or item.get("mapping_id")
        measurement = by_id.get(mapping_id)
        if not measurement:
            raise ValueError(f"unknown mapping {mapping_id}")
        target = item.get("target_measurement")
        if not target or target not in proposal.get("old_columns", []):
            raise ValueError(f"mapping {mapping_id} needs a valid target measurement")
        record = copy.deepcopy(measurement)
        record["target_measurement"] = target
        record["target_unit_column"] = (item.get("target_unit_column") or
                                        record.get("target_unit_column"))
        record["fixed_unit"] = item.get("fixed_unit")
        record["status"] = "confirmed"
        record["rule_status"] = "reusable_after_confirmation"
        result[mapping_id] = record
    return list(result.values())


def effective_mappings(proposal, confirmed):
    mappings = confirmed_map(proposal, confirmed)
    explicit = {m["id"] for m in mappings}
    for measurement in proposal.get("measurements", []):
        if measurement["id"] not in explicit and measurement.get("status") == "inherited":
            record = copy.deepcopy(measurement)
            record["status"] = "inherited"
            mappings.append(record)
    return mappings


def materialize_rows(old_columns, raw_rows, confirmed_mappings,
                     unresolved_targets=None):
    """Build canonical rows only from explicitly confirmed mappings."""
    target_columns = list(old_columns)
    for mapping in confirmed_mappings:
        target = mapping["target_measurement"]
        if target not in target_columns:
            target_columns.append(target)
        unit_target = mapping.get("target_unit_column")
        if unit_target and unit_target not in target_columns:
            target_columns.append(unit_target)

    rows = []
    unresolved_targets = unresolved_targets or []
    for raw in raw_rows:
        row = {"_id": raw["_id"]}
        for col in target_columns:
            row[col] = ""
        provenance = []
        for mapping in confirmed_mappings:
            value_col = mapping["value_column"]
            target = mapping["target_measurement"]
            raw_text = raw.get(value_col, "")
            row[target] = raw_text
            unit_explanation = ""
            if mapping.get("unit_columns"):
                unit_col = mapping["unit_columns"][0]
                unit_text = raw.get(unit_col, "")
                unit_target = mapping.get("target_unit_column") or target + "_unit"
                if unit_target not in row:
                    row[unit_target] = ""
                    target_columns.append(unit_target)
                row[unit_target] = unit_text
                unit_explanation = f"单位来自逐条记录列 {unit_col}={unit_text}"
            elif mapping.get("fixed_unit"):
                unit_explanation = f"固定单位 {mapping['fixed_unit']}"
            provenance.append({
                "mapping_id": mapping["id"],
                "source_columns": mapping["source_columns"],
                "target_measurement": target,
                "original_text": raw_text,
                "representation": mapping["representation"],
                "unit_explanation": unit_explanation,
            })
        mapped_sources = {c for m in confirmed_mappings for c in m["source_columns"]}
        for col, value in raw.items():
            if col == "_id" or col in mapped_sources:
                continue
            inherited = next((m for m in confirmed_mappings
                              if m.get("status") == "inherited"
                              and m["value_column"] == col), None)
            if inherited:
                row[col] = value
                provenance.append({
                    "mapping_id": inherited["id"],
                    "source_columns": inherited["source_columns"],
                    "target_measurement": inherited["target_measurement"],
                    "original_text": value,
                    "representation": "direct",
                    "unit_explanation": "",
                    "inherited": True,
                })
            elif col in target_columns:
                row[col] = value
        row["_structure_provenance"] = provenance
        row["_unresolved_measurements"] = list(unresolved_targets)
        rows.append(row)
    return rows, target_columns


def mapping_action(mapping):
    sources = ", ".join(mapping["source_columns"])
    text = f"结构对应：{sources} → {mapping['target_measurement']}"
    if mapping.get("unit_columns"):
        text += "；单位按逐条记录解释"
    elif mapping.get("fixed_unit"):
        text += f"；固定单位 {mapping['fixed_unit']}"
    return text


def compare_plans(proposal_a, proposal_b, raw_rows, old_columns, spec=None):
    map_a = confirmed_map(proposal_a, proposal_a.get("confirmed"))
    map_b = confirmed_map(proposal_b, proposal_b.get("confirmed"))
    rows_a, cols_a = materialize_rows(old_columns, raw_rows, map_a)
    rows_b, cols_b = materialize_rows(old_columns, raw_rows, map_b)
    by_source_a = {tuple(m["source_columns"]): m for m in map_a}
    by_source_b = {tuple(m["source_columns"]): m for m in map_b}
    structure = []
    for source in sorted(set(by_source_a) | set(by_source_b)):
        a = by_source_a.get(source)
        b = by_source_b.get(source)
        if a != b:
            structure.append({
                "source_columns": list(source),
                "plan_a_target": a and a["target_measurement"],
                "plan_b_target": b and b["target_measurement"],
            })
    rule_diff = []
    ruled = rule_measurement_columns((spec or {}).get("steps"))
    for target in sorted(ruled):
        before = [r["_id"] for r in rows_a if r.get(target)]
        after = [r["_id"] for r in rows_b if r.get(target)]
        if before != after:
            rule_diff.append({"measurement": target,
                              "plan_a_rows": before, "plan_b_rows": after})
    ids_a = {r["_id"] for r in rows_a}
    data_added = sorted(r["_id"] for r in rows_b if r["_id"] not in ids_a)
    a_by_id = {r["_id"]: r for r in rows_a}
    value_changes = []
    for row in rows_b:
        before = a_by_id.get(row["_id"])
        if not before:
            continue
        changed = [c for c in sorted(set(cols_a) | set(cols_b))
                   if before.get(c, "") != row.get(c, "")]
        if changed:
            value_changes.append({"row_id": row["_id"], "columns": changed})
    return {
        "structure_interpretation": structure,
        "cleaning_rule_differences": rule_diff,
        "data_added": data_added,
        "value_changes": value_changes,
    }


def dependent_exception_scopes(exceptions, batch, mapping):
    target = mapping.get("target_measurement")
    scopes = []
    for key, item in (exceptions or {}).items():
        if item.get("batch") != batch or not item.get("active", True):
            continue
        scope = ":" + item.get("scope", "") + ":"
        if target and f":{target}:" in scope:
            scopes.append(key)
        if item.get("mapping_id") == mapping.get("id"):
            scopes.append(key)
    return sorted(set(scopes))
