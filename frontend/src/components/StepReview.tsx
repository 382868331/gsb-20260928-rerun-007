import { Check, Undo2, AlertTriangle } from "lucide-react";
import type { PreviewResult, Row, StepEffect } from "../types";

interface Props {
  preview: PreviewResult;
  accepted: boolean[];
  onAccept: (index: number) => void;
  onReject: (index: number) => void;
}

const ACTION_LABEL: Record<string, string> = {
  converted: "单位换算",
  filled: "缺失填充",
  dropped: "删行",
  merged: "重复合并",
  kept: "保留",
  abort: "中止",
};

export function describeAction(action: string, detail: Record<string, any>): string {
  switch (action) {
    case "converted":
      return `${detail.column}: ${fmt(detail.from_value)}${detail.from_unit} → ${fmt(detail.value)}${detail.to_unit}`;
    case "filled":
      return `${detail.column}: 缺失 → ${fmt(detail.value)}（${detail.strategy === "fill_mean" ? "均值" : detail.strategy === "fill_median" ? "中位数" : detail.strategy === "fill_mode" ? "众数" : "固定值"}）`;
    case "dropped":
      return `因列缺失删除：${(detail.missing_columns ?? []).join(", ")}`;
    case "merged": {
      const src = (detail.source_row_ids ?? []).join(", ");
      const cols = (detail.resolved_columns ?? [])
        .map((c: any) => `${c.column}(${c.strategy === "mean" ? `均值=${fmt(c.value)}` : c.strategy})`)
        .join("; ");
      return `合并 ${src}${cols ? `；冲突列：${cols}` : "；值一致"}`;
    }
    default:
      return "本步未改动";
  }
}

function fmt(v: unknown): string {
  if (typeof v === "number") return String(Math.round(v * 1e6) / 1e6);
  return String(v);
}

export function StepReview({ preview, accepted, onAccept, onReject }: Props) {
  return (
    <div className="review-flow">
      {preview.reports.map((report, i) => {
        const stage = preview.stages[i];
        const effects = new Map<string, StepEffect>(
          (report.stats.effects ?? []).map((e) => [e.row_id, e])
        );
        // rows dropped by this step are not in stage rows; still show ids
        const dropped = (report.stats.effects ?? []).filter((e) => e.action === "dropped");
        const isAccepted = accepted[i];
        const canDecide = i === 0 || accepted[i - 1];
        return (
          <div key={i} className={`step-review ${isAccepted ? "accepted" : ""}`}>
            <div className="report-head">
              <span className="step-index">{i + 1}</span>
              <strong>{report.label}</strong>
              <span className="muted small">
                {report.row_count_before} 行 → {report.row_count_after} 行
              </span>
              {isAccepted && <span className="badge ok"><Check size={12} /> 已接受</span>}
              <span className="spacer" />
              {canDecide && !isAccepted && (
                <button className="btn small primary" onClick={() => onAccept(i)}>
                  <Check size={13} /> 接受本步
                </button>
              )}
              {isAccepted && (
                <button className="btn small" onClick={() => onReject(i)} title="退回后需重新预览后续步骤">
                  <Undo2 size={13} /> 退回
                </button>
              )}
            </div>
            <ul className="stat-list">
              {Object.entries(report.stats)
                .filter(([k]) => k !== "effects")
                .map(([k, v]) => (
                  <li key={k}><code>{k}</code>: {formatStat(v)}</li>
                ))}
            </ul>
            {canDecide || isAccepted ? (
              <>
                <StageTable rows={stage?.rows ?? []} effects={effects} columns={Object.keys(stage?.rows?.[0] ?? {}).filter((c) => c !== "_id")} />
                {dropped.map((e) => (
                  <p key={e.row_id} className="dropped-note">
                    <AlertTriangle size={13} /> {e.row_id} 已删除：{describeAction(e.action, e.detail)}
                  </p>
                ))}
                {stage?.truncated && (
                  <p className="muted small">仅展示前 {stage.rows.length} 行，共 {stage.row_count} 行</p>
                )}
              </>
            ) : (
              <p className="muted small">请先接受上一步，再查看本步预览。</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StageTable({
  rows,
  effects,
  columns,
}: {
  rows: Row[];
  effects: Map<string, StepEffect>;
  columns: string[];
}) {
  return (
    <div className="table-wrap compact">
      <table>
        <thead>
          <tr>
            <th className="mono">_id</th>
            {columns.map((c) => <th key={c}>{c}</th>)}
            <th>本步处理</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const effect = effects.get(row._id);
            return (
              <tr key={row._id} className={effect ? `row-${effect.action}` : ""}>
                <td className="mono">{row._id}</td>
                {columns.map((c) => <td key={c}>{String(row[c] ?? "")}</td>)}
                <td className="small">
                  {effect ? (
                    <span className={`chip action-${effect.action}`}>
                      {ACTION_LABEL[effect.action] ?? effect.action}
                    </span>
                  ) : (
                    <span className="muted">未改动</span>
                  )}
                </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function formatStat(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map((v) => typeof v === "object" ? JSON.stringify(v) : String(v)).join(", ") : "[]";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}
