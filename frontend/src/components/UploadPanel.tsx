import { useState } from "react";
import { api } from "../types";

export function UploadPanel({ onCreated }: { onCreated: (id: string) => void }) {
  const [name, setName] = useState("实验批次 2026-09");
  const [csvText, setCsvText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const pickFile = async (file: File | undefined) => {
    if (!file) return;
    setCsvText(await file.text());
  };

  const submit = async () => {
    setError("");
    setBusy(true);
    try {
      const dataset = await api.createDataset(name, csvText);
      onCreated(dataset.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>1. 接收本地数据</h2>
      <p className="hint">上传后仅生成不可变原件版本 v1，所有清洗规则都作用在新版本上。</p>
      <label className="field">
        数据集名称
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="field">
        本地 CSV 文件
        <input type="file" accept=".csv,text/csv" onChange={(event) => pickFile(event.target.files?.[0])} />
      </label>
      <textarea
        rows={8}
        placeholder="或直接粘贴 CSV（首行为列名）"
        value={csvText}
        onChange={(event) => setCsvText(event.target.value)}
      />
      {error && <p className="error">{error}</p>}
      <button disabled={busy || !csvText.trim()} onClick={submit}>
        {busy ? "创建中…" : "创建原件版本"}
      </button>
    </section>
  );
}
