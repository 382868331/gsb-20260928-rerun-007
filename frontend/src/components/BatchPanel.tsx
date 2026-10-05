import { useState } from "react";
import { PackagePlus } from "lucide-react";
import { api } from "../api";
import type { MeasurementMapping, PipelineStep } from "../types";

interface Props {
  project: string;
  steps: PipelineStep[];
  appended: { _id: string; batch: number; label?: string; columns?: string[] }[];
  mappings: Record<string, MeasurementMapping>;
  onAppended: () => void;
  onMappingsChanged: () => void;
}

const STATUS_TEXT: Record<string, string> = {
  reusable: "可沿用", needs_mapping: "需确认", ambiguous: "存在歧义",
  conflicting: "存在矛盾", missing: "缺少对应", confirmed: "已确认",
};

export function BatchPanel({ project, steps, appended, mappings,
                             onAppended, onMappingsChanged }: Props) {
  const [csv, setCsv] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState<Record<number, MeasurementMapping[]>>({});
  const [choices, setChoices] = useState<Record<string, { value: string; unit: string; defaultUnit: string }>>({});
  const batchNos = Array.from(new Set(appended.map((item) => item.batch))).sort();

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await api.appendBatch(project, csv, label);
      setCsv("");
      setLabel("");
      onAppended();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function inspect(batch: number) {
    setError("");
    try {
      const result = await api.analyzeBatchMappings(project, batch, steps);
      setAnalysis((old) => ({ ...old, [batch]: result.mappings }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function confirm(batch: number, item: MeasurementMapping) {
    const saved = Object.values(mappings).find((m) =>
      m.batch === batch && m.target_column === item.target_column);
    const choice = choices[item.target_column] || {};
    const valueColumn = choice.value || item.value_columns?.[0] || "";
    const unitColumn = choice.unit || item.unit_column || item.unit_candidates?.[0] || "";
    const defaultUnit = choice.defaultUnit || saved?.default_unit || item.default_unit || "";
    setError("");
    try {
      await api.confirmBatchMapping(project, batch, {
        target_column: item.target_column,
        value_column: valueColumn,
        unit_column: unitColumn || undefined,
        default_unit: defaultUnit || undefined,
      });
      onMappingsChanged();
      await inspect(batch);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function revoke(batch: number, item: MeasurementMapping) {
    if (!item.id) return;
    setError("");
    try {
      await api.revokeBatchMapping(project, batch, item.id);
      onMappingsChanged();
      await inspect(batch);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <h2><PackagePlus size={16} /> 追加实验批次与测量对应</h2>
      <p className="small muted">
        新批次可以改变列结构。列名相同不代表测量相同；拆分列、逐条单位和多个候选测量都必须显式确认。
      </p>
      <input placeholder="批次说明（如 2026-10 批次）" value={label}
        onChange={(e) => setLabel(e.target.value)} />
      <textarea rows={6} placeholder="粘贴新批次 CSV（含表头）" value={csv}
        onChange={(e) => setCsv(e.target.value)} />
      <div className="row">
        <button className="btn primary" disabled={busy || !csv.trim()} onClick={submit}>
          追加批次（不影响已发布版本）
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      {batchNos.map((batch) => {
        const rows = appended.filter((item) => item.batch === batch);
        return (
          <div key={batch} className="rule-card" style={{ marginTop: 12 }}>
            <div className="row">
              <strong>批次 {batch}</strong>
              <span className="muted small">{rows.length} 条记录：{rows.map((r) => r._id).join(", ")}</span>
              <button className="btn" onClick={() => inspect(batch)}>分析结构对应</button>
            </div>
            <div className="small muted">新列：{rows[0]?.columns?.join(", ") || "未知"}</div>
            {(analysis[batch] || []).map((item) => {
              const saved = Object.values(mappings).find((m) =>
                m.batch === batch && m.target_column === item.target_column);
              return (
                <div key={item.target_column} className="rule-card">
                  <strong>{item.target_column}：{STATUS_TEXT[saved ? "confirmed" : item.status] || item.status}</strong>
                  <p className="small muted">{item.reason}</p>
                  {item.status !== "reusable" && (
                    <div className="row">
                      <label className="small">数值列
                        <select value={choices[item.target_column]?.value || ""}
                          onChange={(e) => setChoices((old) => ({
                            ...old,
                            [item.target_column]: {
                              value: e.target.value,
                              unit: old[item.target_column]?.unit || "",
                              defaultUnit: old[item.target_column]?.defaultUnit || "",
                            },
                          }))}>
                          <option value="">请选择</option>
                          {(item.candidate_columns || []).map((column) =>
                            <option key={column} value={column}>{column}</option>)}
                        </select>
                      </label>
                      <label className="small">单位列
                        <select value={choices[item.target_column]?.unit || item.unit_column || ""}
                          onChange={(e) => setChoices((old) => ({
                            ...old,
                            [item.target_column]: {
                              value: old[item.target_column]?.value || "",
                              unit: e.target.value,
                              defaultUnit: old[item.target_column]?.defaultUnit || "",
                            },
                          }))}>
                          <option value="">无/固定单位</option>
                          {(item.unit_candidates || []).map((column) =>
                            <option key={column} value={column}>{column}</option>)}
                        </select>
                      </label>
                      <label className="small">默认单位（仅逐行单位为空时生效）
                        <input
                          value={choices[item.target_column]?.defaultUnit ?? saved?.default_unit ?? ""}
                          placeholder="如 C"
                          onChange={(e) => setChoices((old) => ({
                            ...old,
                            [item.target_column]: {
                              value: old[item.target_column]?.value || "",
                              unit: old[item.target_column]?.unit || "",
                              defaultUnit: e.target.value,
                            },
                          }))} />
                      </label>
                      <button className="btn primary" onClick={() => confirm(batch, item)}>确认对应</button>
                      {saved && <button className="btn" onClick={() => revoke(batch, saved)}>撤回</button>}
                    </div>
                  )}
                  {saved && (
                    <p className="small muted">
                      已确认：数值列 {saved.value_column || saved.value_columns?.[0]}
                      {saved.unit_column ? `；逐行单位列 ${saved.unit_column}` : "；无逐行单位列"}
                      {saved.default_unit ? `；整列默认单位 ${saved.default_unit}` : ""}
                      。撤回后重新确认会保留以上选择。
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}
