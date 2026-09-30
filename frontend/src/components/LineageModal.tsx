import { useEffect, useState } from "react";
import { X, GitBranch } from "lucide-react";
import { api } from "../api";
import type { Row } from "../types";

interface Props {
  project: string;
  version: number;
  rowId: string;
  onClose: () => void;
}

export function LineageModal({ project, version, rowId, onClose }: Props) {
  const [origins, setOrigins] = useState<string[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [timeline, setTimeline] = useState<{ step: string; description: string }[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .lineage(project, version, rowId)
      .then((res) => {
        setOrigins(res.origins);
        setRows(res.origin_rows);
        setTimeline(res.timeline ?? []);
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
        <div className="timeline-box">
          <span className="small muted">该结果在各步骤中采用的处理：</span>
          {timeline.length === 0 ? (
            <p className="muted small">无（原始记录未被任何步骤改动）</p>
          ) : (
            <ol className="timeline-list">
              {timeline.map((item, i) => (
                <li key={i}>
                  <span className="badge">{item.step}</span>
                  <span>{item.description}</span>
                </li>
              ))}
            </ol>
          )}
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
