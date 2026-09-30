import { Trash2, GripVertical } from "lucide-react";
import type { PipelineStep, StepType } from "../types";

const STEP_TYPES: { value: StepType; label: string; hint: string }[] = [
  { value: "missing_values", label: "缺失值处理", hint: "删除或填充缺失单元格" },
  { value: "number_check", label: "数值有效性检查", hint: "区分缺失/非法文字/无穷/越界，按来源设置策略" },
  { value: "unit_convert", label: "单位换算", hint: "混排单位归一到标准单位" },
  { value: "dedup_merge", label: "重复记录合并", hint: "按主键合并冲突记录" },
];

const ISSUES = [
  { key: "missing", label: "缺失" },
  { key: "illegal", label: "非法文字" },
  { key: "nonfinite", label: "无穷/NaN" },
  { key: "out_of_range", label: "超出有限范围" },
] as const;

type IssueKey = (typeof ISSUES)[number]["key"];

interface PolicyRow {
  key: IssueKey;
  label: string;
}

function PolicyTable({
  issues,
  value,
  onChange,
  defaults,
}: {
  issues: readonly PolicyRow[];
  value: Record<string, { action?: string; replacement?: number }> | undefined;
  onChange: (next: Record<string, unknown>) => void;
  defaults?: Partial<Record<string, string>>;
}) {
  const policies = value ?? {};
  const fallbackAction = (issue: string) => defaults?.[issue] ?? "error";
  const setPolicy = (issue: string, patch: Record<string, unknown>) =>
    onChange({ ...policies, [issue]: { ...(policies[issue] ?? {}), ...patch } });
  return (
    <table className="rules-table">
      <thead>
        <tr><th>异常来源</th><th>处理策略</th><th>明确替代值</th></tr>
      </thead>
      <tbody>
        {issues.map(({ key, label }) => {
          const entry = policies[key] ?? {};
          return (
            <tr key={key}>
              <td>{label}</td>
              <td>
                <select
                  value={(entry.action as string) ?? fallbackAction(key)}
                  onChange={(e) => setPolicy(key, { action: e.target.value })}
                >
                  <option value="error">中止执行</option>
                  <option value="flag">保留待核对</option>
                  <option value="drop">排除该行</option>
                  <option value="replace">使用替代值</option>
                </select>
              </td>
              <td>
                <input
                  type="number"
                  step="any"
                  disabled={entry.action !== "replace"}
                  value={entry.replacement ?? ""}
                  placeholder="必填有限数值"
                  onChange={(e) =>
                    setPolicy(key, { replacement: e.target.value === "" ? undefined : Number(e.target.value) })}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ColumnPicker({ columns, selected, onToggle }: {
  columns: string[];
  selected: string[];
  onToggle: (col: string) => void;
}) {
  return <CheckboxList columns={columns} selected={selected} onToggle={onToggle} />;
}

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

      {step.type === "number_check" && (
        <div className="step-body">
          <div>
            <span className="small muted">检查列（不选 = 全部列）</span>
            <ColumnPicker
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
            允许下限（有限值，可空）
            <input type="number" step="any" value={String(p.min_value ?? "")}
              placeholder="例如 -273.15"
              onChange={(e) => update({ min_value: e.target.value || null })} />
          </label>
          <label>
            允许上限（有限值，可空）
            <input type="number" step="any" value={String(p.max_value ?? "")}
              onChange={(e) => update({ max_value: e.target.value || null })} />
          </label>
          <div>
            <span className="small muted">
              按异常来源分别设置；替代值必须明确填写，系统不会改成 0。
            </span>
            <PolicyTable
              issues={ISSUES}
              value={p.policies as Record<string, { action?: string; replacement?: number }>}
              onChange={(policies) => update({ policies })}
              defaults={{ missing: "flag" }}
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
          <div>
            <span className="small muted">换算前有效性（原值检查，替代值按标准单位填写）</span>
            <PolicyTable
              issues={ISSUES}
              value={p.policies as Record<string, { action?: string; replacement?: number }>}
              onChange={(policies) => update({ policies })}
              defaults={{ missing: "flag" }}
            />
            <label>
              原值允许下限（可空）
              <input type="number" step="any" value={String(p.min_value ?? "")}
                onChange={(e) => update({ min_value: e.target.value || null })} />
            </label>
            <label>
              原值允许上限（可空）
              <input type="number" step="any" value={String(p.max_value ?? "")}
                onChange={(e) => update({ max_value: e.target.value || null })} />
            </label>
          </div>
          <div>
            <span className="small muted">换算后有效性（结果必须有限且落在范围内）</span>
            <PolicyTable
              issues={ISSUES.filter((i) => i.key === "nonfinite" || i.key === "out_of_range")}
              value={p.post_policies as Record<string, { action?: string; replacement?: number }>}
              onChange={(post_policies) => update({ post_policies })}
            />
            <label>
              结果允许下限（可空）
              <input type="number" step="any" value={String(p.post_min_value ?? "")}
                onChange={(e) => update({ post_min_value: e.target.value || null })} />
            </label>
            <label>
              结果允许上限（可空）
              <input type="number" step="any" value={String(p.post_max_value ?? "")}
                onChange={(e) => update({ post_max_value: e.target.value || null })} />
            </label>
          </div>
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
