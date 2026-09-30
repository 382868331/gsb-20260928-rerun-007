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
import { PreviewPanel } from "./components/PreviewPanel";
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
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
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
    api.getVersion(project, version).then((res) => {
      setRows(res.rows);
      setColumns(res.columns);
    });
  }

  function invalidatePreview() {
    setPreview(null);
    setAccepted(new Set());
  }

  function patchSteps(next: PipelineStep[]) {
    setSteps(next);
    invalidatePreview();
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
      setPreview(await api.preview(project, steps));
      setAccepted(new Set());
    } catch (e) {
      setError(`预览失败，未改动任何数据：${(e as Error).message}`);
      invalidatePreview();
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
      invalidatePreview();
      openVersion(res.version);
    } catch (e) {
      setError(`执行失败，未发布新版本：${(e as Error).message}`);
    } finally {
      setBusy(false);
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
              <button className="btn" onClick={() =>
                fetch("/sample.csv").then((r) => r.text()).then(setCsvText)
                  .catch(() => setError("示例文件不可用，请手工粘贴"))}>
                载入示例（单位混用 + 重复冲突）
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
                  patchSteps(steps.map((x) => (x.id === s.id ? s : x)))}
                onRemove={() => patchSteps(steps.filter((x) => x.id !== step.id))}
              />
            ))}
            <div className="row">
              <button className="btn" onClick={() => patchSteps([...steps, newStep("missing_values")])}>
                <Plus size={14} /> 缺失值处理
              </button>
              <button className="btn" onClick={() => patchSteps([...steps, newStep("unit_convert")])}>
                <Plus size={14} /> 单位换算
              </button>
              <button className="btn" onClick={() => patchSteps([...steps, newStep("dedup_merge")])}>
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
                <Eye size={15} /> 预览影响
              </button>
              <button className="btn" disabled={!steps.length || busy} onClick={runPreview}
                title="修改或退回后重新计算全部下游预览">
                <RefreshCw size={15} /> 重新计算预览
              </button>
              <button
                className="btn primary"
                disabled={!steps.length || busy || !preview || accepted.size !== steps.length}
                onClick={apply}
                title={preview && accepted.size === steps.length ? "" : "请先预览并逐步接受全部步骤"}
              >
                <Play size={15} /> 执行并生成新版本
              </button>
            </div>
            {error && <p className="error">{error}</p>}
          </section>

          {preview && (
            <section className="card">
              <h2>执行前预览（不写盘）</h2>
              <PreviewPanel
                preview={preview}
                accepted={accepted}
                onAccept={(i) => {
                  const next = new Set(accepted);
                  next.add(i);
                  setAccepted(next);
                }}
                onReject={(i) => {
                  const removed = steps[i];
                  patchSteps(steps.filter((s) => s.id !== removed.id));
                }}
              />
              <DataTable rows={preview.sample} columns={columns} />
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
