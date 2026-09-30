import { useEffect, useState } from "react";
import { FlaskConical, Plus, Play, Eye, Upload, RefreshCw } from "lucide-react";
import { api } from "./api";
import type {
  Manifest,
  PipelineStep,
  PreviewResult,
  Row,
  StepType,
} from "./types";
import { StepEditor } from "./components/StepEditor";
import { StepReview } from "./components/StepReview";
import { DataTable } from "./components/DataTable";
import { VersionHistory } from "./components/VersionHistory";
import { LineageModal } from "./components/LineageModal";

let stepSeq = 0;
const newStep = (type: StepType): PipelineStep => ({
  id: `s${Date.now()}-${stepSeq++}`,
  type,
  params: type === "dedup_merge" ? { merge: "mean", on_conflict: "keep_all" } : {},
});

export default function App() {
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState("");
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [columns, setColumns] = useState<string[]>([]);
  const [viewVersion, setViewVersion] = useState(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [accepted, setAccepted] = useState<boolean[]>([]);
  const [traceRow, setTraceRow] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState("");
  const [csvText, setCsvText] = useState("");

  useEffect(() => {
    api.listProjects().then((r) => setProjects(r.projects)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!project) return;
    api.getProject(project).then((info) => {
      setManifest(info.manifest);
      setColumns(info.columns);
      openVersion(info.manifest.latest_version);
    });
  }, [project]);

  function openVersion(version: number) {
    setViewVersion(version);
    setPreview(null);
    setAccepted([]);
    api.getVersion(project, version).then((res) => {
      setRows(res.rows);
      setColumns(res.columns);
    });
  }

  async function upload() {
    setError("");
    try {
      await api.createProject(newName.trim(), csvText);
      const r = await api.listProjects();
      setProjects(r.projects);
      setProject(newName.trim());
      setCsvText("");
      setNewName("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function runPreview() {
    setError("");
    setBusy(true);
    try {
      const res = await api.preview(project, steps);
      setPreview(res);
      setAccepted((prev) =>
        res.reports.map((_, i) => prev[i] === true)
      );
    } catch (e) {
      setError(`预览失败，未改动任何数据：${(e as Error).message}`);
      setPreview(null);
      setAccepted([]);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    setError("");
    setBusy(true);
    try {
      const res = await api.apply(project, label, steps);
      const info = await api.getProject(project);
      setManifest(info.manifest);
      setSteps([]);
      setLabel("");
      setPreview(null);
      setAccepted([]);
      openVersion(res.version);
    } catch (e) {
      setError(`执行失败，未发布新版本：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  function editSteps(next: PipelineStep[]) {
    setSteps(next);
    setPreview(null);
    setAccepted([]);
  }

  function acceptStep(index: number) {
    setAccepted((prev) => prev.map((a, i) => (i === index ? true : a)));
  }

  function rejectStep(index: number) {
    // 退回本步：本步及其下游的旧预览全部失效，必须重新预览；上游保留
    setAccepted((prev) => prev.map((a, i) => (i < index ? a : false)));
    setPreview(null);
  }

  async function loadSample(key: string) {
    setError("");
    try {
      const s = await api.sample(key);
      setCsvText(s.csv);
    } catch (e) {
      setError(`示例文件不可用：${(e as Error).message}`);
    }
  }

  if (!project) {
    return (
      <div className="page">
        <Header />
        <div className="layout">
          <section className="card">
            <h2>
              <Upload size={16} /> 导入本地 CSV
            </h2>
            <input
              placeholder="工程名称（如 lab-2026-09）"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <textarea
              rows={10}
              placeholder="粘贴 CSV 内容（第一行表头）"
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
            />
            <div className="row">
              <button className="btn primary" onClick={upload}
                disabled={!newName.trim() || !csvText.trim()}>
                <Plus size={15} /> 创建工程
              </button>
              <button className="btn" onClick={() => loadSample("clean")}>
                载入示例（单位混用 + 重复冲突）
              </button>
              <button className="btn" onClick={() => loadSample("bad")}
                title="额外含一行非法温度值，用于验证失败不发布">
                载入含非法值的示例
              </button>
            </div>
            {error && <p className="error">{error}</p>}
          </section>
          <section className="card">
            <h2>已有工程（重开可继续查看）</h2>
            {projects.length === 0 && <p className="muted">暂无工程</p>}
            {projects.map((name) => (
              <button key={name} className="project-item" onClick={() => setProject(name)}>
                <FlaskConical size={15} /> {name}
              </button>
            ))}
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <Header project={project} onHome={() => setProject("")} />
      <div className="layout with-history">
        {manifest && (
          <VersionHistory
            manifest={manifest}
            selected={viewVersion}
            onSelect={openVersion}
          />
        )}
        <main className="main-col">
          <section className="card">
            <h2>处理流水线（v{manifest?.latest_version} → 新版本）</h2>
            {steps.map((step, i) => (
              <StepEditor
                key={step.id}
                step={step}
                index={i}
                columns={columns}
                onChange={(s) =>
                  editSteps(steps.map((x) => (x.id === s.id ? s : x)))}
                onRemove={() => editSteps(steps.filter((x) => x.id !== step.id))}
              />
            ))}
            <div className="row">
              <button className="btn" onClick={() => editSteps([...steps, newStep("missing_values")])}>
                <Plus size={14} /> 缺失值处理
              </button>
              <button className="btn" onClick={() => editSteps([...steps, newStep("unit_convert")])}>
                <Plus size={14} /> 单位换算
              </button>
              <button className="btn" onClick={() => editSteps([...steps, newStep("dedup_merge")])}>
                <Plus size={14} /> 重复合并
              </button>
            </div>
            <div className="row">
              <input
                placeholder="本版本说明（可选）"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            <div className="row">
              <button className="btn" disabled={!steps.length || busy} onClick={runPreview}>
                {preview ? <RefreshCw size={15} /> : <Eye size={15} />}
                {preview ? "重新预览全部步骤" : "预览全部步骤"}
              </button>
              <button
                className="btn primary"
                disabled={!steps.length || busy || !preview ||
                  accepted.length !== steps.length || !accepted.every(Boolean)}
                onClick={apply}
                title={preview && accepted.every(Boolean) ? "" : "请逐步预览并接受每一步"}
              >
                <Play size={15} /> 执行并生成新版本
              </button>
            </div>
            {preview && (
              <p className="muted small">
                已接受 {accepted.filter(Boolean).length}/{steps.length} 步；
                退回任意一步后，旧的下游结果立即失效，需重新预览。
              </p>
            )}
            {error && <p className="error">{error}</p>}
          </section>

          {preview && (
            <section className="card">
              <h2>
                <Eye size={16} /> 逐步预览（不写盘）：行数 {preview.row_count_before} → {preview.row_count_after}
              </h2>
              <StepReview
                preview={preview}
                accepted={accepted}
                onAccept={acceptStep}
                onReject={rejectStep}
              />
            </section>
          )}

          <section className="card">
            <h2>当前查看：v{viewVersion} 数据（{rows.length} 行）</h2>
            <DataTable
              rows={rows}
              columns={columns}
              version={viewVersion}
              onTrace={viewVersion === 0 ? undefined : setTraceRow}
            />
          </section>
        </main>
      </div>
      {traceRow && (
        <LineageModal
          project={project}
          version={viewVersion}
          rowId={traceRow}
          onClose={() => setTraceRow(null)}
        />
      )}
    </div>
  );
}

function Header({ project, onHome }: { project?: string; onHome?: () => void }) {
  return (
    <header className="topbar">
      <h1 onClick={onHome} className="clickable">
        <FlaskConical size={20} /> 实验数据清洗工作台
      </h1>
      {project && <span className="muted">工程：{project}</span>}
    </header>
  );
}
