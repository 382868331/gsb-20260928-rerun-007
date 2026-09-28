import type { PreviewResult } from "../types";

export function PreviewPanel({ preview }: { preview: PreviewResult }) {
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
      </div>
      <ol className="report-list">
        {preview.reports.map((r, i) => (
          <li key={i} className="report-item">
            <div className="report-head">
              <span className="step-index">{i + 1}</span>
              <strong>{r.label}</strong>
              <span className="muted small">
                {r.row_count_before} 行 → {r.row_count_after} 行
              </span>
            </div>
            <ul className="stat-list">
              {Object.entries(r.stats).map(([k, v]) => (
                <li key={k}>
                  <code>{k}</code>: {formatStat(v)}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
    </div>
  );
}

function formatStat(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "[]";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value);
}
