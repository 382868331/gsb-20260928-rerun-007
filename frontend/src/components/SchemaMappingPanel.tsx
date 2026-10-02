import { useState } from "react";
import { GitMerge, RotateCcw } from "lucide-react";
import { api } from "../api";
import type { SchemaBatch } from "../types";

interface Props {
  project: string;
  batches: SchemaBatch[];
  oldColumns: string[];
  onChange: () => void;
}

const statusLabel: Record<string, string> = {
  suggested: "建议但待确认",
  ambiguous: "多个合理对应，待确认",
  new_measurement: "新测量",
  inherited: "同名直通，已自动保留解释",
  revoked: "已撤回",
  confirmed: "已确认",
};

export function SchemaMappingPanel({ project, batches, oldColumns, onChange }: Props) {
  const changed = batches.filter((b) => b.schema_status === "changed");
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  if (!changed.length) return null;

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusyId(id);
    setError("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="card">
      <h2><GitMerge size={16} /> 结构变化批次的测量对应</h2>
      <p className="small muted">
        列名不会自动决定含义。请逐条确认测量及单位；未确认范围不会进入预览或发布。
      </p>
      {changed.map((batch) => {
        const byId = new Map(batch.proposal?.measurements.map((m) => [m.id, m]));
        const confirmed = new Set(batch.confirmed_ids);
        return (
          <div className="rule-card" key={batch.batch}>
            <h3>批次 {batch.batch}：{batch.label}</h3>
            <p className="small muted">
              原始列：{batch.proposal?.new_columns.join("、")}
            </p>
            {batch.proposal?.measurements.map((mapping) => {
              const isConfirmed = confirmed.has(mapping.id);
              const target = batch.confirmed.find((m) => m.id === mapping.id)
                ?.target_measurement || mapping.target_measurement || "";
              const unitTarget = batch.confirmed.find((m) => m.id === mapping.id)
                ?.target_unit_column || mapping.target_unit_column || "";
              return (
                <div className="mapping-row" key={mapping.id}>
                  <div>
                    <strong>{mapping.source_columns.join(" + ")}</strong>
                    <span className="muted small">
                      {" "}→ {statusLabel[mapping.status] || mapping.status}
                    </span>
                    <div className="small muted">
                      规则状态：{mapping.rule_status}；样例：
                      {JSON.stringify(mapping.sample_values)}
                    </div>
                  </div>
                  {mapping.status === "inherited" ? (
                    <span className="small">自动继承身份列</span>
                  ) : (
                    <div className="row">
                      <select
                        defaultValue={target}
                        disabled={isConfirmed || busyId === mapping.id}
                        onChange={(e) => {
                          mapping.target_measurement = e.target.value;
                        }}
                      >
                        <option value="">选择旧测量…</option>
                        {(mapping.candidate_measurements.length
                          ? mapping.candidate_measurements : oldColumns)
                          .map((c) => <option key={c} value={c}>{c}</option>)}
                      </select>
                      <input
                        placeholder="单位列（可选）"
                        defaultValue={unitTarget}
                        disabled={isConfirmed || busyId === mapping.id}
                        onChange={(e) => {
                          mapping.target_unit_column = e.target.value;
                        }}
                      />
                      {!isConfirmed ? (
                        <button
                          className="btn primary"
                          disabled={busyId === mapping.id || !mapping.target_measurement}
                          onClick={() => run(mapping.id, () =>
                            api.confirmMappings(project, batch.batch, [{
                              id: mapping.id,
                              target_measurement: mapping.target_measurement!,
                              target_unit_column: mapping.target_unit_column || undefined,
                            }]))}
                        >
                          确认此对应
                        </button>
                      ) : (
                        <button
                          className="btn"
                          disabled={busyId === mapping.id}
                          onClick={() => run(mapping.id, () =>
                            api.revokeMapping(project, batch.batch, mapping.id))}
                        >
                          <RotateCcw size={14} /> 撤回并重检
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
            <p className="small">
              待确认：{batch.pending_ids.length ? batch.pending_ids.join(", ") : "无"}
            </p>
          </div>
        );
      })}
      {error && <p className="error">{error}</p>}
    </section>
  );
}

