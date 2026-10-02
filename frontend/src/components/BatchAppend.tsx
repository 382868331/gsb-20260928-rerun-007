import { useState } from "react";
import { Layers } from "lucide-react";
import type { Manifest } from "../types";

interface Props {
  manifest: Manifest;
  onAppended: () => void;
  appendBatch: (csv: string, label: string) => Promise<void>;
}

export function BatchAppend({ manifest, onAppended, appendBatch }: Props) {
  const [open, setOpen] = useState(false);
  const [csv, setCsv] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const batches = manifest.batches ?? [];

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await appendBatch(csv, label);
      setCsv("");
      setLabel("");
      setOpen(false);
      onAppended();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>
        <button className="linklike" onClick={() => setOpen(!open)}>
          <Layers size={16} /> 追加实验批次（同一套来源规则）
        </button>
      </h2>
      <p className="muted small">
        已发布版本永不被覆盖；新批次进入工作数据集，重新预览/发布时生成追加版本。
        当前工作数据集第 {manifest.working_generation ?? 1} 代，共 {batches.length} 个批次。
      </p>
      <ul className="batch-list">
        {batches.map((b) => (
          <li key={b.generation} className="small">
            第 {b.generation} 代 · {b.label || "未命名"} · {b.row_count} 行
            （{b.row_ids.join(", ")}）
          </li>
        ))}
      </ul>
      {open && (
        <div>
          <input
            placeholder="批次说明（可选）"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <textarea
            rows={6}
            placeholder="粘贴新批次 CSV（表头必须与现有数据一致）"
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
          />
          <div className="row">
            <button
              className="btn primary"
              disabled={!csv.trim() || busy}
              onClick={submit}
            >
              追加批次
            </button>
            <button className="btn" onClick={() => setOpen(false)}>
              取消
            </button>
          </div>
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </section>
  );
}
