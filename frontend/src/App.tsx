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
import { BatchPanel } from "./components/BatchPanel";
import { ExceptionsPanel } from "./components/ExceptionsPanel";
import type { ManualException } from "./types";

let stepSeq = 0;
const newStep = (type: StepType): PipelineStep => ({
  id: `s${Date.now()}-${stepSeq++}`,
  type,
  params: type === "dedup_merge"
    ? { merge: "mean", on_conflict: "keep_all" }
    : type === "number_check"
      ? { policies: {} }
      : {},
});

export default function App() {
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState("");
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [columns, setColumns] = useState<string[]>([]);
  const [viewVersion, setViewVersion] = useState(0);
  const [sourceVersion, setSourceVersion] = useState(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [traceRow, setTraceRow] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [exceptions, setExceptions] = useState<Record<string, ManualException>>({});
  const [appended, setAppended] = useState<{ _id: string; batch: number; label?: string; columns?: string[] }[]>([]);
  const [mappings, setMappings] = useState<Record<string, import("./types").MeasurementMapping>>({});
  const [includeAppended, setIncludeAppended] = useState(true);

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
      setExceptions(info.exceptions ?? {});
      setAppended(info.appended ?? []);
      setMappings(info.mappings ?? {});
      openVersion(info.manifest.latest_version);
      setSourceVersion(info.manifest.latest_version);
    });
  }, [project]);

  function refreshProject() {
    api.getProject(project).then((info) => {
      setManifest(info.manifest);
      setExceptions(info.exceptions ?? {});
      setAppended(info.appended ?? []);
      setMappings(info.mappings ?? {});
    });
  }

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
      setPreview(await api.preview(project, steps, sourceVersion,
        { includeAppended, useExceptions: true }));
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
      const res = await api.apply(project, label, steps, sourceVersion,
        { includeAppended, useExceptions: true });
      const info = await api.getProject(project);
      setManifest(info.manifest);
      setExceptions(info.exceptions ?? {});
      setAppended(info.appended ?? []);
      setMappings(info.mappings ?? {});
      setSteps([]);
      setLabel("");
      invalidatePreview();
      setSourceVersion(res.version);
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
            <h2>处理流水线（v{sourceVersion} → 新版本）</h2>
            <label className="small muted">
              基于版本（可选择历史成功版本分叉对比，旧版本保持原样）
              <select
                value={sourceVersion}
                onChange={(e) => {
                  setSourceVersion(Number(e.target.value));
                  invalidatePreview();
                }}
              >
                {manifest?.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}{v.label ? ` - ${v.label}` : ""}
                  </option>
                ))}
              </select>
            </label>
            {appended.length > 0 && (
              <label className="small">
                <input
                  type="checkbox"
                  checked={includeAppended}
                  onChange={(e) => {
                    setIncludeAppended(e.target.checked);
                    invalidatePreview();
                  }}
                />
                包含 {appended.length} 条追加批次记录一起预览/发布（不重写已发布版本）
              </label>
            )}
            {steps.map((step, i) => (
              <StepEditor
                key={step.id}
                step={step}
                index={i}
                columns={columns}
                project={project}
                onResolveConflict={async (rowId, scope, keepManual) => {
                  if (!keepManual) {
                    await api.revokeException(project, rowId, scope);
                  }
                  refreshProject();
                  invalidatePreview();
                }}
                onChange={(s) =>
                  patchSteps(steps.map((x) => (x.id === s.id ? s : x)))}
                onRemove={() => patchSteps(steps.filter((x) => x.id !== step.id))}
              />
            ))}
            <div className="row">
              <button className="btn" onClick={() => patchSteps([...steps, newStep("missing_values")])}>
                <Plus size={14} /> 缺失值处理
              </button>
              <button className="btn" onClick={() => patchSteps([...steps, newStep("number_check")])}>
                <Plus size={14} /> 数值有效性检查
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
                project={project}
                preview={preview}
                accepted={accepted}
                onAccept={(i) => {
                  const next = new Set(accepted);
                  next.add(i);
                  setAccepted(next);
                }}
                onReject={(i) => {
                  const cleaningIndex = preview.reports
                    .slice(0, i + 1)
                    .filter((r) => r.type !== "schema_mapping").length - 1;
                  const removed = steps[cleaningIndex];
                  if (removed) patchSteps(steps.filter((s) => s.id !== removed.id));
                }}
                onExceptionChanged={refreshProject}
              />
              <DataTable rows={preview.sample} columns={columns} />
              {(preview.unmapped_rows?.length || 0) > 0 && (
                <div className="warning-box">
                  <strong>尚未确定的记录：</strong>
                  {preview.unmapped_rows?.map((row) => row._id).join(", ")}
                  <ul className="small muted" style={{ margin: "4px 0" }}>
                    {preview.unmapped_rows?.map((row) => (
                      <li key={row._id}>
                        {row._id}：
                        {Array.isArray(row._missing_targets) && (row._missing_targets as string[]).length > 0
                          ? `仍待确认测量 ${(row._missing_targets as string[]).join(", ")}`
                          : "尚未确认任何测量对应"}
                        {row._mapping_status === "partial" ? "（部分测量已确认）" : ""}
                      </li>
                    ))}
                  </ul>
                  <div className="small muted">这些记录不参与本次已确认部分预览，也不会进入发布范围。</div>
                </div>
              )}
              {preview.adopted_scope && (
                <p className="small muted">{preview.adopted_scope.note}</p>
              )}
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
          <BatchPanel
            project={project}
            steps={steps}
            appended={appended}
            mappings={mappings}
            onAppended={() => refreshProject()}
            onMappingsChanged={() => refreshProject()}
          />
          {manifest && (
            <ExceptionsPanel
              project={project}
              exceptions={exceptions}
              manifest={manifest}
              onChange={refreshProject}
            />
          )}
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
