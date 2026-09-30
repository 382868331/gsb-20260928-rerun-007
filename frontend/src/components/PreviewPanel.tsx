import { Check, Undo2 } from "lucide-react";
import type { PreviewResult, StepReport } from "../types";

interface Props {
  preview: PreviewResult;
  accepted: Set<number>;
  onAccept: (index: number) => void;
  onReject: (index: number) => void;
}

export function PreviewPanel({ preview, accepted, onAccept, onReject }: Props) {
  const delta = preview.row_count_after - preview.row_count_before;
  return (
    <div className="preview-panel">
      <div className="preview-summary">
        <span>
          {preview.base_version !== undefined ? `基线 v${preview.base_version}：` : ""}
          行数：{preview.row_count_before} → {" "}
          <strong className={delta < 0 ? "danger-text" : ""}>
            {preview.row_count_after}
          </strong>{" "}
          ({delta >= 0 ? "+" : ""}
          {delta})
        </span>
        <span className="muted small">
          已接受 {accepted.size}/{preview.reports.length} 步：请逐步预览受影响行后选择接受或退回
        </span>
      </div>
      <ol className="report-list">
        {preview.reports.map((r, i) => {
          const isAccepted = accepted.has(i);
          return (
          <li key={i} className={`report-item ${isAccepted ? "accepted" : ""}`}>
            <div className="report-head">
              <span className="step-index">{i + 1}</span>
              <strong>{r.label}</strong>
              <span className="muted small">
                {r.row_count_before} 行 → {r.row_count_after} 行
              </span>
              {isAccepted && <span className="badge ok">已接受</span>}
              {!isAccepted && (
                <span className="step-decide">
                  <button className="btn small primary" onClick={() => onAccept(i)}>
                    <Check size={13} /> 接受这一步
                  </button>
                  <button className="btn small" onClick={() => onReject(i)}>
                    <Undo2 size={13} /> 退回这一步
                  </button>
                </span>
              )}
            </div>
            <ul className="stat-list">
              {Object.entries(r.stats).map(([k, v]) => (
                <li key={k}>
                  {k !== "affected_rows" && (
                    <>
                      <code>{k}</code>: {formatStat(v)}
                    </>
                  )}
                </li>
              ))}
            </ul>
            <AffectedRows report={r} />
          </li>
          );
        })}
      </ol>
    </div>
  );
}

function AffectedRows({ report }: { report: StepReport }) {
  const rows = (report.stats.affected_rows as unknown[]) ?? [];
  if (!rows.length) return <p className="muted small">本步骤不改变任何行。</p>;
  return (
    <div className="affected-box">
      <span className="small muted">受影响的 {rows.length} 行预览（执行前不写盘）：</span>
      <ul className="affected-list">
        {(report.actions ?? []).map((action, i) => (
          <li key={i} className="affected-item">
            <code>{action.origins.join(", ")}</code>
            <span>{action.description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatStat(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "[]";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}
