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
import { BatchAppend } from "./components/BatchAppend";
import { ComparePanel } from "./components/ComparePanel";
import { ExceptionPanel } from "./components/ExceptionPanel";
import { ExceptionDialog } from "./components/ExceptionDialog";

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
  // -1 means the accumulated working dataset (includes appended batches);
  // an explicit version number forks from that immutable publication.
  const [sourceVersion, setSourceVersion] = useState(-1);
  const [rows, setRows] = useState<Row[]>([]);
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [label, setLabel] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [accepted, setAccepted] = useState<Set<number>>(new Set());
  const [traceRow, setTraceRow] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflictChoices, setConflictChoices] = useState<
    Record<string, "keep" | "withdraw">
  >({});
  const [exceptionVersion, setExceptionVersion] = useState(0);
  const [exceptionRow, setExceptionRow] = useState<string | null>(null);

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
      setSourceVersion(-1);
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
      setPreview(await api.preview(
        project, steps, sourceVersion < 0 ? undefined : sourceVersion));
      setAccepted(new Set());
      setConflictChoices({});
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
      const conflicts = preview?.conflicts ?? [];
      const unresolved = conflicts.filter((c) => !conflictChoices[c.id]);
      if (conflicts.length > 0 && unresolved.length > 0) {
        setError("人工例外与新规则冲突：请逐条选择保留或撤回后再发布。");
        setBusy(false);
        return;
      }
      const res = await api.apply(
        project, label, steps,
        sourceVersion < 0 ? undefined : sourceVersion,
        conflictChoices);
      const info = await api.getProject(project);
      setManifest(info.manifest);
      setSteps([]);
      setLabel("");
      invalidatePreview();
      setSourceVersion(-1);
      setExceptionVersion((n) => n + 1);
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
            <h2>
              处理流水线（{sourceVersion < 0 ? "工作数据集" : `v${sourceVersion}`} → 新版本）
            </h2>
            <label className="small muted">
              基于数据：工作数据集含已追加但尚未发布的批次；选择历史版本则从该版本分叉，旧版本保持原样
              <select
                value={sourceVersion}
                onChange={(e) => {
                  setSourceVersion(Number(e.target.value));
                  invalidatePreview();
                }}
              >
                <option value={-1}>
                  工作数据集（第 {manifest?.working_generation ?? 1} 代，含新批次）
                </option>
                {manifest?.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}{v.label ? ` - ${v.label}` : ""}
                  </option>
                ))}
              </select>
            </label>
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

          {manifest && (
            <BatchAppend
              manifest={manifest}
              onAppended={async () => {
                const info = await api.getProject(project);
                setManifest(info.manifest);
                setColumns(info.columns);
              invalidatePreview();
              openVersion(info.manifest.latest_version);
              setSourceVersion(-1);
              }}
              appendBatch={async (csvText, batchLabel) => {
                await api.appendBatch(project, csvText, batchLabel || undefined);
              }}
            />
          )}

          {preview && (
            <section className="card">
              <h2>执行前预览（不写盘）</h2>
              <p className="small muted">
                旧记录 {preview.old_record_count ?? preview.row_count_before} 行，
                新批次记录 {preview.new_record_count ?? 0} 行；
                下表逐条标注来源决定（全局/来源规则/人工例外）与是否新记录。
              </p>
              {(preview.conflicts ?? []).length > 0 && (
                <ConflictBox
                  conflicts={preview.conflicts!}
                  choices={conflictChoices}
                  onChoose={(id, choice) =>
                    setConflictChoices((prev) => ({ ...prev, [id]: choice }))}
                />
              )}
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
              onException={steps.length ? setExceptionRow : undefined}
            />
          </section>

          <ExceptionPanel
            project={project}
            changed={exceptionVersion + (manifest?.latest_version ?? 0)}
            listExceptions={() => api.listExceptions(project)}
            withdrawException={(id) => api.withdrawException(project, id)}
          />

          {manifest && (
            <ComparePanel
              manifest={manifest}
              compare={(x, y) => api.compareVersions(project, x, y)}
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
      {exceptionRow && (
        <ExceptionDialog
          rowId={exceptionRow}
          steps={steps}
          onClose={() => setExceptionRow(null)}
          onSubmit={async (payload) => {
            await api.saveException(project, payload);
            setExceptionVersion((n) => n + 1);
            invalidatePreview();
          }}
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

function ConflictBox({
  conflicts,
  choices,
  onChoose,
}: {
  conflicts: import("./types").RuleConflict[];
  choices: Record<string, "keep" | "withdraw">;
  onChoose: (id: string, choice: "keep" | "withdraw") => void;
}) {
  return (
    <div className="conflict-box">
      <strong>人工例外与当前规则冲突，请重新选择：</strong>
      <table className="rules-table">
        <thead>
          <tr><th>记录</th><th>列/异常</th><th>原人工决定</th><th>是否保留</th></tr>
        </thead>
        <tbody>
          {conflicts.map((c) => (
            <tr key={c.id}>
              <td className="mono">{c.row_id}</td>
              <td>{c.column} · {c.issue}</td>
              <td>{c.manual_action === "replace" ? "使用替代值"
                : c.manual_action === "drop" ? "排除该行"
                : c.manual_action === "flag" ? "保留待核对" : c.manual_action}</td>
              <td>
                <select
                  value={choices[c.id] ?? ""}
                  onChange={(e) =>
                    onChoose(c.id, e.target.value as "keep" | "withdraw")}
                >
                  <option value="" disabled>请选择…</option>
                  <option value="keep">保留人工例外</option>
                  <option value="withdraw">撤回，改用新规则</option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
