import { useState } from "react";
import { PackagePlus } from "lucide-react";
import { api } from "../api";
import type { Row } from "../types";

interface Props {
  project: string;
  appended: { _id: string; batch: number; label?: string }[];
  onAppended: (newRows: Row[]) => void;
}

export function BatchPanel({ project, appended, onAppended }: Props) {
  const [csv, setCsv] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastIds, setLastIds] = useState<string[]>([]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const res = await api.appendBatch(project, csv, label);
      setLastIds(res.new_ids);
      setCsv("");
      setLabel("");
      onAppended(res.new_rows);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2><PackagePlus size={16} /> 追加新到实验批次</h2>
      <p className="small muted">
        列结构必须与原始 CSV 一致；追加只进入工作区，不覆盖任何已发布版本。
      </p>
      <input
        placeholder="批次说明（如 2026-10 批次）"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
      />
      <textarea
        rows={6}
        placeholder={"粘贴新批次 CSV（含表头）"}
        value={csv}
        onChange={(e) => setCsv(e.target.value)}
      />
      <div className="row">
        <button className="btn primary" disabled={busy || !csv.trim()} onClick={submit}>
          追加批次（不影响已发布版本）
        </button>
        {lastIds.length > 0 && (
          <span className="muted small">
            已追加 {lastIds.length} 行：{lastIds.join(", ")}
          </span>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {appended.length > 0 && (
        <p className="muted small">
          当前工作区共含追加记录 {appended.length} 条（
          {appended.map((a) => a._id).join(", ")}）。
          发布时勾选「包含追加批次」即可在同一套来源规则下一起清洗。
        </p>
      )}
    </section>
  );
}
