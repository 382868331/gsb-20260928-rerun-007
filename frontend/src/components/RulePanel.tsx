import { PipelineSpec } from "../types";

type Props = {
  columns: string[];
  spec: PipelineSpec;
  onChange: (spec: PipelineSpec) => void;
};

export function RulePanel({ columns, spec, onChange }: Props) {
  const toggle = (key: keyof PipelineSpec) => {
    onChange({ ...spec, [key]: spec[key] ? null : defaultRules(key, columns) });
  };

  const update = (key: keyof PipelineSpec, patch: Record<string, unknown>) => {
    const current = spec[key] ?? ({} as Record<string, unknown>);
    onChange({ ...spec, [key]: { ...current, ...patch } });
  };

  const missing = spec.missing;
  const unit = spec.unit;
  const merge = spec.merge;

  return (
    <section className="card">
      <h2>2. 配置处理步骤</h2>
      <p className="hint">按顺序执行：缺失值处理 → 单位换算 → 重复记录合并。</p>

      <StepToggle title="缺失值处理" enabled={!!missing} onToggle={() => toggle("missing")}>
        <div className="row">
          <label>策略
            <select value={missing?.strategy ?? "mean"} onChange={(e) => update("missing", { strategy: e.target.value })}>
              <option value="mean">均值填充（数值列）</option>
              <option value="median">中位数填充（数值列）</option>
              <option value="constant">固定值填充</option>
              <option value="drop_row">删除含缺失的行</option>
            </select>
          </label>
          <label>目标列（空=全部数值列）
            <select value={missing?.column ?? ""} onChange={(e) => update("missing", { column: e.target.value || null })}>
              <option value="">全部数值列</option>
              {columns.map((column) => <option key={column} value={column}>{column}</option>)}
            </select>
          </label>
          {missing?.strategy === "constant" && (
            <label>填充值
              <input type="number" onChange={(e) => update("missing", { fill_value: Number(e.target.value) })} />
            </label>
          )}
        </div>
      </StepToggle>

      <StepToggle title="单位换算" enabled={!!unit} onToggle={() => toggle("unit")}>
        <div className="row">
          <label>数值列
            <select value={unit?.column ?? ""} onChange={(e) => update("unit", { column: e.target.value })}>
              {columns.map((column) => <option key={column}>{column}</option>)}
            </select>
          </label>
          <label>单位列
            <select value={unit?.unit_column ?? ""} onChange={(e) => update("unit", { unit_column: e.target.value })}>
              {columns.map((column) => <option key={column}>{column}</option>)}
            </select>
          </label>
          <label>目标单位
            <input value={unit?.target_unit ?? ""} onChange={(e) => update("unit", { target_unit: e.target.value })} />
          </label>
        </div>
        <ConversionEditor unit={unit} onPatch={(patch) => update("unit", patch)} />
      </StepToggle>

      <StepToggle title="重复记录合并" enabled={!!merge} onToggle={() => toggle("merge")}>
        <div className="row">
          <fieldset className="keys">
            <legend>合并键（相同键视为同一实验）</legend>
            {columns.map((column) => (
              <label key={column} className="check">
                <input
                  type="checkbox"
                  checked={merge?.keys.includes(column) ?? false}
                  onChange={(e) => {
                    const keys = new Set(merge?.keys ?? []);
                    e.target.checked ? keys.add(column) : keys.delete(column);
                    update("merge", { keys: [...keys] });
                  }}
                />
                {column}
              </label>
            ))}
          </fieldset>
          <label>数值冲突策略
            <select value={merge?.conflict ?? "mean"} onChange={(e) => update("merge", { conflict: e.target.value })}>
              <option value="mean">取均值</option>
              <option value="first">取第一条</option>
              <option value="last">取最后一条</option>
            </select>
          </label>
        </div>
      </StepToggle>
    </section>
  );
}

function StepToggle({ title, enabled, onToggle, children }: {
  title: string; enabled: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  return (
    <div className={`step ${enabled ? "on" : ""}`}>
      <label className="step-head">
        <input type="checkbox" checked={enabled} onChange={onToggle} />
        <strong>{title}</strong>
      </label>
      {enabled && children}
    </div>
  );
}

function ConversionEditor({ unit, onPatch }: {
  unit: PipelineSpec["unit"]; onPatch: (patch: Record<string, unknown>) => void;
}) {
  const conversions = unit?.conversions ?? {};
  const entries = Object.entries(conversions);
  const addRow = () => {
    const next = { ...conversions, "": 1 };
    onPatch({ conversions: next });
  };
  const removeRow = (name: string) => {
    const next = { ...conversions };
    delete next[name];
    onPatch({ conversions: next });
  };
  const rename = (oldName: string, name: string, factor: number) => {
    const next = { ...conversions };
    delete next[oldName];
    next[name] = factor;
    onPatch({ conversions: next });
  };

  return (
    <div className="conversions">
      <p className="hint">系数 = 1 个原单位等于多少目标单位；例如 mmHg → kPa 填 0.1333224。</p>
      {entries.map(([name, factor]) => (
        <div className="row" key={name}>
          <input defaultValue={name} onBlur={(e) => rename(name, e.target.value, factor)} placeholder="原单位，如 bar" />
          <input type="number" step="any" value={factor} onChange={(e) => rename(name, name, Number(e.target.value))} placeholder="系数" />
          <button className="ghost" onClick={() => removeRow(name)}>删除</button>
        </div>
      ))}
      <button className="ghost" onClick={addRow}>+ 添加换算系数</button>
    </div>
  );
}

function defaultRules(key: keyof PipelineSpec, columns: string[]) {
  if (key === "missing") return { strategy: "mean", column: null, fill_value: null };
  if (key === "unit") {
    const numeric = columns[0] ?? "";
    return { column: numeric, unit_column: columns[1] ?? "", conversions: {}, target_unit: "" };
  }
  return { keys: columns.slice(0, 1), conflict: "mean" };
}
