import { useState } from "react";
import { api, PipelineSpec, PreviewResponse } from "../types";
import { DataTable } from "./DataTable";

export function PreviewPanel({
  datasetId, baseVersion, columns, spec, onCommitted,
}: {
  datasetId: string;
  baseVersion: string;
  columns: string[];
  spec: PipelineSpec;
  onCommitted: () => void;
}) {
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const enabledSteps = ["missing", "unit", "merge"].filter((key) => spec[key as keyof PipelineSpec]);
  const canRun = enabledSteps.length > 0 && enabledSteps.every((key) => {
    if (key === "unit") {
      const unit = spec.unit!;
      return unit.column && unit.unit_column && unit.target_unit && Object.keys(unit.conversions).length > 0;
    }
    if (key === "merge") return spec.merge!.keys.length > 0;
    return true;
  });

  const runPreview = async () => {
    setError("");
    setBusy(true);
    try {
      setPreview(await api.preview(datasetId, baseVersion, spec));
    } catch (err) {
      setPreview(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setError("");
    setBusy(true);
    try {
      await api.commit(datasetId, baseVersion, note || `基于 ${baseVersion} 的规则版本`, spec);
      setPreview(null);
      onCommitted();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <h2>3. 预览影响并发布</h2>
      <p className="hint">基于版本 <code>{baseVersion}</code> 试算；只有显式发布才会生成新版本，原件永不修改。</p>
      <div className="row">
        <button disabled={!canRun || busy} onClick={runPreview}>预览影响</button>
        {preview && (
          <>        <input placeholder="版本说明（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="primary" disabled={busy} onClick={commit}>确认执行，发布新版本</button>
          </>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {preview && (
        <div>
          <div className="metrics">
            <Metric label="处理前行数" value={preview.preview.rows_before} />
            <Metric label="处理后行数" value={preview.preview.rows_after} />
          </div>
          <div className="reports">
            {preview.reports.map((report) => (
              <div className="report" key={report.step}>
                <strong>{STEP_NAMES[report.step]}</strong>
                <span>影响 {report.changed_rows} 行</span>
                <code>{JSON.stringify(report.detail)}</code>
              </div>
            ))}
          </div>
          <h3>处理后（前 8 行，附来源原记录 ID）</h3>
          <DataTable columns={columns} rows={preview.preview.after} />
        </div>
      )}
    </section>
  );
}

const STEP_NAMES: Record<string, string> = {
  missing: "缺失值处理", unit: "单位换算", merge: "重复记录合并",
};

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="metric">
      <span className="metric-value">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}
