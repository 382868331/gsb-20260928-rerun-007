import { Info } from "lucide-react";
import type { Row } from "../types";

interface Props {
  rows: Row[];
  columns: string[];
  version?: number;
  onTrace?: (rowId: string) => void;
  maxRows?: number;
  highlightIds?: Set<string>;
}

export function DataTable({ rows, columns, version, onTrace, maxRows, highlightIds }: Props) {
  const shown = maxRows ? rows.slice(0, maxRows) : rows;
  const hasReview = rows.some((r) => Array.isArray(r._review) && r._review.length);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th className="mono">_id</th>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
            {hasReview ? <th>待核对</th> : null}
            {onTrace ? <th>来源</th> : null}
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => {
            const review = Array.isArray(row._review) ? (row._review as string[]) : [];
            const flaggedCols = new Set(review.map((tag) => tag.split(":")[0]));
            const cells = columns.map((c) => (
              <td key={c} className={flaggedCols.has(c) ? "review-cell" : undefined}>
                {String(row[c] ?? "")}
              </td>
            ));
            return (
              <tr key={row._id} className={highlightIds?.has(row._id) ? "affected-row" : undefined}>
                <td className="mono">{row._id}</td>
                {cells}
                {hasReview ? (
                  <td>{review.length ? <span className="badge warn">待核对</span> : null}</td>
                ) : null}
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
