import { useEffect, useState } from "react";
import { X, GitBranch } from "lucide-react";
import { api } from "../api";
import type { Row, Treatment } from "../types";
import { describeAction } from "./StepReview";

interface Props {
  project: string;
  version: number;
  rowId: string;
  onClose: () => void;
}

export function LineageModal({ project, version, rowId, onClose }: Props) {
  const [origins, setOrigins] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [cleanRow, setCleanRow] = useState<Row | null>(null);
  const [treatments, setTreatments] = useState<Treatment[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .lineage(project, version, rowId)
      .then((res) => {
        setOrigins(res.origins);
        setRows(res.origin_rows);
        setCleanRow(res.clean_row);
        setTreatments(res.treatments);
      })
      .catch((e: Error) => setError(e.message));
  }, [project, version, rowId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>
            <GitBranch size={16} /> 血缘追溯 · 结果行 {rowId}
          </h3>
          <button className="icon-btn" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        <p className="muted small">
          该结果来自 <strong>{origins.length}</strong> 条原始记录（v0 不可变快照）：
          {origins.map((id) => (
            <span key={id} className="chip mono">
              {id}
            </span>
          ))}
        </p>
        {cleanRow && (
          <div className="clean-row-box">
            <strong>清洗后的值（结果行 {rowId}）</strong>
            <ul className="stat-list">
              {Object.entries(cleanRow)
                .filter(([k]) => k !== "_id")
                .map(([k, v]) => (
                  <li key={k}><code>{k}</code>: {String(v)}</li>
                ))}
            </ul>
          </div>
        )}
        <div className="treatments-box">
          <strong>采用的处理（{treatments.length} 步）</strong>
          {treatments.length === 0 && (
            <p className="muted small">无处理记录。</p>
          )}
          <ol className="treatment-list">
            {treatments.map((t) => (
              <li key={t.step} className={`treatment treatment-${t.action}`}>
                <span className="step-index">{t.step}</span>
                <span className="treatment-label">{t.label}</span>
                <span className="small muted">{describeAction(t.action, t.detail)}</span>
                <span className="chip mono small">{t.origins.join(", ")}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>原始行号</th>
                {rows[0] &&
                  Object.keys(rows[0])
                    .filter((k) => k !== "_id")
                    .map((k) => <th key={k}>{k}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row._id}>
                  <td className="mono">{row._id}</td>
                  {Object.entries(row)
                    .filter(([k]) => k !== "_id")
                    .map(([k, v]) => (
                      <td key={k}>{String(v)}</td>
                    ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
