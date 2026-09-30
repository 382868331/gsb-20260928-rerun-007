import { Trash2, GripVertical } from "lucide-react";
import type { AnomalyKind, AnomalyRule, PipelineStep, StepType } from "../types";

const STEP_TYPES: { value: StepType; label: string; hint: string }[] = [
  { value: "missing_values", label: "缺失值处理", hint: "删除或填充缺失单元格" },
  { value: "unit_convert", label: "单位换算", hint: "混排单位归一到标准单位" },
  { value: "dedup_merge", label: "重复记录合并", hint: "按主键合并冲突记录" },
  { value: "validate_numbers", label: "数值有效性检查", hint: "按来源区分缺失 / 非法文字 / 超范围" },
];

interface Props {
  step: PipelineStep;
  index: number;
  columns: string[];
  onChange: (step: PipelineStep) => void;
  onRemove: () => void;
}

function CheckboxList({
  columns,
  selected,
  onToggle,
}: {
  columns: string[];
  selected: string[];
  onToggle: (col: string) => void;
}) {
  return (
    <div className="checkbox-list">
      {columns.map((col) => (
        <label key={col} className="chip">
          <input
            type="checkbox"
            checked={selected.includes(col)}
            onChange={() => onToggle(col)}
          />
          {col}
        </label>
      ))}
    </div>
  );
}

export function StepEditor({ step, index, columns, onChange, onRemove }: Props) {
  const p = step.params;
  const update = (patch: Record<string, unknown>) =>
    onChange({ ...step, params: { ...p, ...patch } });

  const meta = STEP_TYPES.find((t) => t.value === step.type);

  return (
    <div className="step-card">
      <div className="step-head">
        <GripVertical size={16} className="muted" />
        <select
          value={step.type}
          onChange={(e) =>
            onChange({ ...step, type: e.target.value as StepType, params: {} })
          }
        >
          {STEP_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {index + 1}. {t.label}
            </option>
          ))}
        </select>
        <span className="muted small">{meta?.hint}</span>
        <button className="icon-btn danger" onClick={onRemove} title="删除步骤">
          <Trash2 size={15} />
        </button>
      </div>

      {step.type === "missing_values" && (
        <div className="step-body">
          <label>
            策略
            <select
              value={(p.strategy as string) ?? "drop_row"}
              onChange={(e) => update({ strategy: e.target.value })}
            >
              <option value="drop_row">删除含缺失值的整行</option>
              <option value="fill_constant">固定值填充</option>
              <option value="fill_mean">均值填充（数值列）</option>
              <option value="fill_median">中位数填充（数值列）</option>
              <option value="fill_mode">众数填充</option>
            </select>
          </label>
          {p.strategy === "fill_constant" && (
            <label>
              填充值
              <input
                value={String(p.fill_value ?? "")}
                onChange={(e) => update({ fill_value: e.target.value })}
                placeholder="例如 0 或 N/A"
              />
            </label>
          )}
          <div>
            <span className="small muted">作用列（不选 = 全部列）</span>
            <CheckboxList
              columns={columns}
              selected={(p.columns as string[]) ?? []}
              onToggle={(col) => {
                const current = new Set((p.columns as string[]) ?? []);
                current.has(col) ? current.delete(col) : current.add(col);
                update({ columns: [...current] });
              }}
            />
          </div>
        </div>
      )}

      {step.type === "unit_convert" && (
        <div className="step-body">
          <label>
            数值列
            <select
              value={(p.column as string) ?? ""}
              onChange={(e) => update({ column: e.target.value })}
            >
              <option value="">选择列…</option>
              {columns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            单位来源
            <select
              value={(p.unit_column as string) ?? ""}
              onChange={(e) => update({ unit_column: e.target.value || null })}
            >
              <option value="">无单位列（统一单位）</option>
              {columns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            标准单位
            <input
              value={(p.canonical_unit as string) ?? ""}
              onChange={(e) => update({ canonical_unit: e.target.value })}
              placeholder="例如 C"
            />
          </label>
          <label>
            来源列（按来源设置异常策略，可空）
            <select
              value={(p.source_column as string) ?? ""}
              onChange={(e) => update({ source_column: e.target.value || null })}
            >
              <option value="">不区分来源</option>
              {columns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <AnomalyRulesEditor
            rules={(p.anomaly_rules as AnomalyRule[]) ?? []}
            onChange={(anomalyRules) => update({ anomaly_rules: anomalyRules })}
          />
          <div>
            <span className="small muted">
              换算规则：标准值 = 原始值 × factor + offset（标准单位自身 factor=1）
            </span>
            <table className="rules-table">
              <thead>
                <tr>
                  <th>原单位</th>
                  <th>factor</th>
                  <th>offset</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries((p.rules as Record<string, unknown>) ?? {}).map(
                  ([unit, rule]) => {
                    const entry = typeof rule === "object" ? rule as Record<string, number> : { factor: Number(rule), offset: 0 };
                    return (
                      <tr key={unit}>
                        <td>{unit}</td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            value={entry.factor}
                            onChange={(e) => {
                              const rules = { ...(p.rules as object),
                                [unit]: { ...entry, factor: Number(e.target.value) } };
                              update({ rules });
                            }}
                          />
                        </td>
                        <td>
                          <input
                            type="number"
                            step="any"
                            value={entry.offset ?? 0}
                            onChange={(e) => {
                              const rules = { ...(p.rules as object),
                                [unit]: { ...entry, offset: Number(e.target.value) } };
                              update({ rules });
                            }}
                          />
                        </td>
                      </tr>
                    );
                  }
                )}
              </tbody>
            </table>
            <AddUnit onAdd={(unit, factor, offset) =>
              update({
                canonical_unit: (p.canonical_unit as string) || "",
                rules: {
                  ...((p.rules as object) ?? {}),
                  [unit]: offset === 0 ? factor : { factor, offset },
                },
              })}
            />
          </div>
        </div>
      )}

      {step.type === "validate_numbers" && (
        <div className="step-body">
          <div>
            <span className="small muted">需要为有限数值的列</span>
            <CheckboxList
              columns={columns}
              selected={(p.columns as string[]) ?? []}
              onToggle={(col) => {
                const current = new Set((p.columns as string[]) ?? []);
                current.has(col) ? current.delete(col) : current.add(col);
                update({ columns: [...current] });
              }}
            />
          </div>
          <label>
            来源列（可空；填写后可按来源分别设置策略）
            <select
              value={(p.source_column as string) ?? ""}
              onChange={(e) => update({ source_column: e.target.value || null })}
            >
              <option value="">不区分来源</option>
              {columns.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <AnomalyRulesEditor
            rules={(p.rules as AnomalyRule[]) ?? []}
            onChange={(rules) => update({ rules })}
          />
          <label className="small">
            <input
              type="checkbox"
              checked={p.strict !== false}
              onChange={(e) => update({ strict: e.target.checked })}
            />
            未配置策略的异常一律中止（不发布任何结果）
          </label>
        </div>
      )}

      {step.type === "dedup_merge" && (
        <div className="step-body">
          <div>
            <span className="small muted">主键列（值相同即视为重复）</span>
            <CheckboxList
              columns={columns}
              selected={(p.keys as string[]) ?? []}
              onToggle={(col) => {
                const current = new Set((p.keys as string[]) ?? []);
                current.has(col) ? current.delete(col) : current.add(col);
                update({ keys: [...current] });
              }}
            />
          </div>
          <label>
            数值冲突合并方式
            <select
              value={(p.merge as string) ?? "mean"}
              onChange={(e) => update({ merge: e.target.value })}
            >
              <option value="mean">取平均值</option>
              <option value="first">保留首条</option>
              <option value="last">保留末条</option>
            </select>
          </label>
          <div>
            <span className="small muted">
              参与数值合并的列（不选 = 自动只合并数值列；其他列保留首条）
            </span>
            <CheckboxList
              columns={columns.filter((c) => !((p.keys as string[]) ?? []).includes(c))}
              selected={(p.merge_columns as string[]) ?? []}
              onToggle={(col) => {
                const current = new Set((p.merge_columns as string[]) ?? []);
                current.has(col) ? current.delete(col) : current.add(col);
                update({ merge_columns: [...current] });
              }}
            />
          </div>
          <label>
            非数值冲突时
            <select
              value={(p.on_conflict as string) ?? "keep_all"}
              onChange={(e) => update({ on_conflict: e.target.value })}
            >
              <option value="keep_all">按合并策略保留结果</option>
              <option value="error">中止本次执行（不发布）</option>
            </select>
          </label>
        </div>
      )}
    </div>
  );
}

const ANOMALY_KIND_LABELS: { value: AnomalyKind; label: string }[] = [
  { value: "missing", label: "缺失（空 / N/A）" },
  { value: "invalid", label: "非法文字（如 ERR）" },
  { value: "nonfinite", label: "超出有限范围（inf / NaN / 溢出）" },
];

function AnomalyRulesEditor({
  rules,
  onChange,
}: {
  rules: AnomalyRule[];
  onChange: (rules: AnomalyRule[]) => void;
}) {
  const updateAt = (i: number, patch: Partial<AnomalyRule>) =>
    onChange(rules.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <div className="anomaly-rules">
      <span className="small muted">
        异常处理策略（同一列可按来源分别设置；精确来源优先于“任意来源”）
      </span>
      <table className="rules-table">
        <thead>
          <tr>
            <th>异常类型</th>
            <th>来源（空 = 任意）</th>
            <th>策略</th>
            <th>明确替代值</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rules.map((rule, i) => (
            <tr key={i}>
              <td>
                <select
                  value={rule.kind}
                  onChange={(e) =>
                    updateAt(i, { kind: e.target.value as AnomalyKind })}
                >
                  {ANOMALY_KIND_LABELS.map((k) => (
                    <option key={k.value} value={k.value}>{k.label}</option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  value={rule.source ?? ""}
                  placeholder="任意来源"
                  onChange={(e) => updateAt(i, { source: e.target.value })}
                />
              </td>
              <td>
                <select
                  value={rule.action}
                  onChange={(e) =>
                    updateAt(i, {
                      action: e.target.value as AnomalyRule["action"],
                    })}
                >
                  <option value="flag">保留待核对（不改原值）</option>
                  <option value="drop">排除该行</option>
                  <option value="replace">使用替代值</option>
                </select>
              </td>
              <td>
                <input
                  value={String(rule.value ?? "")}
                  disabled={rule.action !== "replace"}
                  placeholder={rule.action === "replace" ? "必须明确给出" : ""}
                  onChange={(e) => updateAt(i, { value: e.target.value })}
                />
              </td>
              <td>
                <button
                  type="button"
                  className="icon-btn danger"
                  onClick={() => onChange(rules.filter((_, idx) => idx !== i))}
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        className="btn small"
        onClick={() =>
          onChange([
            ...rules,
            { kind: "invalid", source: "", action: "flag" },
          ])}
      >
        添加异常策略
      </button>
    </div>
  );
}

function AddUnit({
  onAdd,
}: {
  onAdd: (unit: string, factor: number, offset: number) => void;
}) {
  return (
    <form
      className="add-unit"
      onSubmit={(e) => {
        e.preventDefault();
        const form = e.currentTarget;
        const data = new FormData(form);
        const unit = String(data.get("unit") ?? "").trim();
        const factor = Number(data.get("factor"));
        const offset = Number(data.get("offset") ?? 0);
        if (unit && !Number.isNaN(factor)) onAdd(unit, factor, offset);
        form.reset();
      }}
    >
      <input name="unit" placeholder="单位名（如 F）" />
      <input name="factor" type="number" step="any" placeholder="factor" />
      <input name="offset" type="number" step="any" placeholder="offset（可空）" />
      <button type="submit" className="btn small">添加规则</button>
    </form>
  );
}
