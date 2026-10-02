import { useState } from "react";
import { X } from "lucide-react";
import type { PipelineStep } from "../types";

const ISSUE_OPTIONS = [
  ["illegal", "非法文字"],
  ["missing", "缺失"],
  ["nonfinite", "非有限数值"],
  ["out_of_range", "超出有限范围"],
] as const;

export function ExceptionDialog({
  rowId,
  steps,
  onClose,
  onSubmit,
}: {
  rowId: string;
  steps: PipelineStep[];
  onClose: () => void;
  onSubmit: (payload: {
    steps: { type: string; params: Record<string, unknown> }[];
    row_id: string;
    column: string;
    issue: string;
    stage?: string;
    action: string;
    replacement?: number;
    reason?: string;
  }) => Promise<void>;
}) {
  const [column, setColumn] = useState("");
  const [issue, setIssue] = useState("illegal");
  const [action, setAction] = useState("flag");
  const [replacement, setReplacement] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      const numericSteps = steps.filter((s) =>
        ["number_check", "unit_convert"].includes(s.type));
      const stepType = numericSteps.find((s) => {
        const params = s.params;
        const cols = (params.columns as string[] | undefined) ?? [];
        return cols.length === 0 || cols.includes(column);
      })?.type;
      await onSubmit({
        steps: steps.map(({ type, params }) => ({ type, params })),
        row_id: rowId,
        column,
        issue,
        stage: stepType === "unit_convert" ? "pre_convert" : "number_check",
        action,
        replacement:
          action === "replace" && replacement !== ""
            ? Number(replacement)
            : undefined,
        reason: reason || undefined,
      });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>为 {rowId} 设置人工例外</strong>
          <button className="icon-btn" onClick={onClose}><X size={15} /></button>
        </div>
        <p className="small muted">
          例外与当前规则指纹一并保存；规则再变化时需重新确认是否保留。
        </p>
        <label>
          列
          <input value={column} onChange={(e) => setColumn(e.target.value)} placeholder="如 temperature" />
        </label>
        <label>
          异常类型
          <select value={issue} onChange={(e) => setIssue(e.target.value)}>
            {ISSUE_OPTIONS.map(([value, text]) => (
              <option key={value} value={value}>{text}</option>
            ))}
          </select>
        </label>
        <label>
          人工决定
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="flag">保留待核对</option>
            <option value="drop">排除该行</option>
            <option value="replace">使用替代值</option>
          </select>
        </label>
        {action === "replace" && (
          <label>
            替代值（必填有限数值）
            <input type="number" step="any" value={replacement}
              onChange={(e) => setReplacement(e.target.value)} />
          </label>
        )}
        <label>
          理由（可选）
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="row">
          <button className="btn primary" disabled={!column || busy} onClick={submit}>
            保存例外
          </button>
          <button className="btn" onClick={onClose}>取消</button>
        </div>
      </div>
    </div>
  );
}
