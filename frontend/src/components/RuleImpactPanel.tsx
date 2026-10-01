import { useState } from "react";
import { GitCompareArrows } from "lucide-react";
import { api } from "../api";
import type { RuleImpact } from "../types";

interface Props {
  project: string;
  hasOldRules: boolean;
  buildOldParams: () => Record<string, unknown>;
  buildNewParams: () => Record<string, unknown>;
  columns: string[];
  onResolveConflict: (rowId: string, scope: string, keepManual: boolean) => void;
}

export function RuleImpactPanel(
  { project, hasOldRules, buildOldParams, buildNewParams, columns,
    onResolveConflict }: Props,
) {
  const [impact, setImpact] = useState<RuleImpact | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function analyze() {
    setBusy(true);
    setError("");
    try {
      const result = await api.ruleImpact(project, {
        step_type: "number_check",
        columns,
        old_params: hasOldRules ? buildOldParams() : {},
        new_params: buildNewParams(),
      });
      setImpact(result as RuleImpact);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rule-impact">
      <button type="button" className="btn small" disabled={busy} onClick={analyze}>
        <GitCompareArrows size={13} /> 规则修改后先列出受影响记录
      </button>
      {error && <p className="error">{error}</p>}
      {impact && (
        <div className="impact-box">
          <p className="small muted">
            旧记录 {impact.changed_decisions.filter((c) => !c.is_new_row).length} 条决定变化，
            新记录 {impact.newly_handled.filter((c) => c.is_new_row).length} 条将被处理。
          </p>
          {impact.changed_decisions.length > 0 && (
            <details open>
              <summary>受影响的旧记录（{impact.changed_decisions.length}）</summary>
              <ul className="affected-list">
                {impact.changed_decisions.map((c) => (
                  <li key={`${c.row_id}-${c.column}-${c.issue}`}>
                    <code>{c.row_id}</code> {c.column} {c.issue_label}
                    原值 {String(c.original_value)}：{c.old_action}
                    {c.old_replacement != null ? ` ${c.old_replacement}` : ""} →
                    <strong>{c.new_action}</strong>
                    {c.new_replacement != null ? ` ${c.new_replacement}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {impact.newly_handled.length > 0 && (
            <details open>
              <summary>新规则覆盖的记录（{impact.newly_handled.length}）</summary>
              <ul className="affected-list">
                {impact.newly_handled.map((c) => (
                  <li key={`${c.row_id}-${c.column}-${c.issue}`}>
                    <code>{c.row_id}</code>{c.is_new_row ? "（新批次）" : ""}
                    {" "}{c.column} {c.issue_label} 原值 {String(c.original_value)}
                    {c.source_value != null ? ` 来源=${String(c.source_value)}` : ""}
                    → {c.action}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {impact.conflicting_exceptions.length > 0 && (
            <div className="conflict-box">
              <p className="error">
                以下人工例外与新规则冲突，请逐条选择保留人工决定还是改用新规则：
              </p>
              <ul>
                {impact.conflicting_exceptions.map((c) => {
                  const scope =
                    `number_check:${c.column}:check:${c.issue}`;
                  return (
                    <li key={`${c.row_id}-${scope}`}>
                      <code>{c.row_id}</code> {scope}：人工 {c.manual_action}
                      vs 新规则 {c.rule_action}（{c.reason}）
                      <button className="btn small" onClick={() =>
                        onResolveConflict(c.row_id, scope, true)}>
                        保留人工决定
                      </button>
                      <button className="btn small" onClick={() =>
                        onResolveConflict(c.row_id, scope, false)}>
                        改用新规则（撤回例外）
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
