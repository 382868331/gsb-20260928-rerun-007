import { Info } from "lucide-react";
import type { AnomalyMarker, Row } from "../types";

interface Props {
  rows: Row[];
  columns: string[];
  version?: number;
  onTrace?: (rowId: string) => void;
  maxRows?: number;
  highlightIds?: Set<string>;
  anomalies?: Record<string, Record<string, AnomalyMarker>>;
}

export function DataTable({ rows, columns, version, onTrace, maxRows, highlightIds, anomalies }: Props) {
  const shown = maxRows ? rows.slice(0, maxRows) : rows;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="mono">_id</th>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
            {onTrace ? <th>来源</th> : null}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => {
            const rowAnomalies = anomalies?.[row._id];
            const cells = columns.map((c) => {
              const marker = rowAnomalies?.[c];
              return (
                <td key={c} className={marker ? "cell-anomaly" : undefined}>
                  {String(row[c] ?? "")}
                  {marker && (
                    <span className={`anomaly-badge ${marker.kind}`} title="保留原值待核对，未当作可用数值">
                      待核对·{marker.kind === "missing" ? "缺失" : marker.kind === "invalid" ? "非法文字" : "超范围"}
                    </span>
                  )}
                </td>
              );
            });
            return (
              <tr key={row._id} className={highlightIds?.has(row._id) ? "affected-row" : undefined}>
                <td className="mono">{row._id}</td>
                {cells}
                {onTrace ? (
                  <td>
                    <button
                      className="icon-btn"
                      title="查看来自哪些原记录"
                      onClick={() => onTrace(row._id)}
                    >
                      <Info size={15} />
                    </button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
      {maxRows && rows.length > maxRows ? (
        <p className="muted small">仅展示前 {maxRows} 行，共 {rows.length} 行</p>
      ) : null}
      {version !== undefined ? (
        <p className="muted small">当前版本 v{version}</p>
      ) : null}
    </div>
  );
}
