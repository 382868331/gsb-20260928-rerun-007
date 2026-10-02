import { Check, Undo2, UserCog } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { PreviewResult, StepReport } from "../types";

interface Props {
  project: string;
  preview: PreviewResult;
  accepted: Set<number>;
  onAccept: (index: number) => void;
  onReject: (index: number) => void;
  onExceptionChanged?: () => void;
}

export function PreviewPanel(
  { project, preview, accepted, onAccept, onReject, onExceptionChanged }: Props,
) {
  const delta = preview.row_count_after - preview.row_count_before;
  return (
    <div className="preview-panel">
      <div className="preview-summary">
        <span>
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
              <AffectedRows
                project={project}
                report={r}
                onExceptionChanged={onExceptionChanged}
              />
          </li>
          );
        })}
      </ol>
    </div>
  );
}

function AffectedRows({ project, report, onExceptionChanged }: {
  project: string; report: StepReport;
  onExceptionChanged?: () => void;
}) {
  const rows = (report.stats.affected_rows as unknown[]) ?? [];
  if (!rows.length) return <p className="muted small">本步骤不改变任何行。</p>;
  return (
    <div className="affected-box">
      <span className="small muted">受影响的 {rows.length} 行预览（执行前不写盘）：</span>
      <ul className="affected-list">
        {(report.actions ?? []).map((action, i) => {
          const detail = action.detail as Record<string, unknown>;
          const scope = scopeForDetail(report.type, detail);
          return (
            <li key={i} className="affected-item">
              <code>{action.origins.join(", ")}</code>
              <span>{String(action.description)}</span>
              {detail.decision_source === "manual" && (
                <span className="badge warn">人工决定</span>
              )}
              {scope && detail.issue ? (
                <ManualButtons
                  project={project}
                  rowId={String(detail.row_id ?? action.origins[0] ?? "")}
                  scope={scope}
                  mappingIds={(Array.isArray(detail.mapping_ids)
                    ? detail.mapping_ids.map(String) : []).filter((id) =>
                    id.endsWith(`:${String(detail.column ?? "")}`))}
                  onChanged={onExceptionChanged}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function scopeForDetail(stepType: string, detail: Record<string, unknown>): string {
  const column = String(detail.column ?? "");
  const issue = String(detail.issue ?? "");
  if (!column || !issue) return "";
  if (stepType === "unit_convert") {
    const stage = detail.stage === "post_convert" ? "post" : "pre";
    return `unit_convert:${column}:${stage}:${issue}`;
  }
  return `number_check:${column}:check:${issue}`;
}

function ManualButtons({ project, rowId, scope, mappingIds, onChanged }: {
  project: string; rowId: string; scope: string; mappingIds: string[];
  onChanged?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  async function decide(action: "flag" | "drop") {
    setBusy(true);
    setSaved("");
    try {
      await api.setException(project, {
        row_id: rowId, scope, action,
        reason: action === "flag" ? "人工保留待核对" : "人工排除",
        mapping_id: mappingIds[0],
      });
      setSaved(action === "flag" ? "已设为待核对" : "已设为排除");
      onChanged?.();
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="manual-decide">
      <UserCog size={13} />
      <button className="btn small" disabled={busy} onClick={() => decide("flag")}>
        人工：保留核对
      </button>
      <button className="btn small" disabled={busy} onClick={() => decide("drop")}>
        人工：排除
      </button>
      {saved && <span className="muted small">{saved}（重新预览后生效）</span>}
    </span>
  );
}

function formatStat(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "[]";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}
