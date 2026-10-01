import { useState } from "react";
import { UserCog, Scale } from "lucide-react";
import { api } from "../api";
import type { Manifest, ManualException } from "../types";

interface Props {
  project: string;
  exceptions: Record<string, ManualException>;
  manifest: Manifest;
  onChange: () => void;
}

const ACTION_LABEL: Record<string, string> = {
  flag: "保留待核对",
  drop: "排除该行",
  replace: "使用替代值",
};

export function ExceptionsPanel({ project, exceptions, manifest, onChange }: Props) {
  const [versionA, setVersionA] = useState(0);
  const [versionB, setVersionB] = useState(
    Math.max(0, manifest.latest_version));
  const [diff, setDiff] = useState<Record<string, string[]> | null>(null);
  const [error, setError] = useState("");

  const items = Object.values(exceptions);

  async function revoke(rowId: string, scope: string) {
    setError("");
    try {
      await api.revokeException(project, rowId, scope);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function runDiff() {
    setError("");
    try {
      const result = await api.diffVersions(project, versionA, versionB);
      setDiff(Object.fromEntries(
        Object.entries(result).map(([k, v]) => [k, v as string[]])));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <h2><UserCog size={16} /> 单条记录人工例外</h2>
      {items.length === 0 && (
        <p className="muted small">暂无人工例外；可在预览或数据表格中对具体记录设置。</p>
      )}
      {items.length > 0 && (
        <table className="rules-table">
          <thead>
            <tr><th>记录</th><th>作用范围</th><th>人工决定</th><th>原因</th><th>状态</th><th /></tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.row_id}|${item.scope}`}
                  className={item.active === false ? "revoked-row" : ""}>
                <td className="mono">{item.row_id}</td>
                <td className="small">{item.scope}</td>
                <td>
                  {ACTION_LABEL[item.action] ?? item.action}
                  {item.action === "replace" && item.replacement != null
                    ? ` ${item.replacement}` : ""}
                </td>
                <td className="small muted">{item.reason}</td>
                <td>{item.active === false ? "已撤回" : "生效中"}</td>
                <td>
                  {item.active !== false && (
                    <button className="btn small" onClick={() =>
                      revoke(item.row_id, item.scope)}>
                      撤回（恢复按规则）
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {error && <p className="error">{error}</p>}

      <h3 style={{ marginTop: 16 }}><Scale size={15} /> 版本对比（区分三类影响）</h3>
      <div className="row">
        <label className="small">
          旧版
          <select value={versionA} onChange={(e) => setVersionA(Number(e.target.value))}>
            {manifest.versions.map((v) => (
              <option key={v.version} value={v.version}>v{v.version}</option>
            ))}
          </select>
        </label>
        <label className="small">
          新版
          <select value={versionB} onChange={(e) => setVersionB(Number(e.target.value))}>
            {manifest.versions.map((v) => (
              <option key={v.version} value={v.version}>v{v.version}</option>
            ))}
          </select>
        </label>
        <button className="btn" onClick={runDiff}>比较</button>
      </div>
      {diff && (
        <ul className="diff-list">
          <li>数据新增：{formatList(diff.data_added)}</li>
          <li>规则变化改值：{formatList(diff.value_changed?.map(
            (v) => typeof v === "string" ? v : JSON.stringify(v)))}</li>
          <li>规则排除：{formatList(diff.dropped_rows)}</li>
          <li>人工决定保留/恢复：{formatList(diff.restored_rows)}</li>
        </ul>
      )}
    </section>
  );
}

function formatList(values: string[] | undefined): string {
  return values && values.length ? values.join(", ") : "无";
}
