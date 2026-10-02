import { useState } from "react";
import { GitCompareArrows } from "lucide-react";
import type { Manifest, VersionComparison } from "../types";

const CAUSE_LABELS: Record<string, string> = {
  data_added: "数据新增",
  rule_changed: "规则变化",
  manual_decision: "人工决定",
};

export function ComparePanel({
  manifest,
  compare,
}: {
  manifest: Manifest;
  compare: (a: number, b: number) => Promise<VersionComparison>;
}) {
  const published = manifest.versions.filter((v) => v.version > 0);
  const [a, setA] = useState(published[0]?.version ?? 0);
  const [b, setB] = useState(published[published.length - 1]?.version ?? 0);
  const [result, setResult] = useState<VersionComparison | null>(null);
  const [error, setError] = useState("");

  if (published.length < 2) return null;

  async function run() {
    setError("");
    try {
      setResult(await compare(a, b));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <section className="card">
      <h2>
        <GitCompareArrows size={16} /> 版本差异归因
      </h2>
      <div className="row">
        <select value={a} onChange={(e) => setA(Number(e.target.value))}>
          {published.map((v) => (
            <option key={v.version} value={v.version}>v{v.version}</option>
          ))}
        </select>
        <span>↔</span>
        <select value={b} onChange={(e) => setB(Number(e.target.value))}>
          {published.map((v) => (
            <option key={v.version} value={v.version}>v{v.version}</option>
          ))}
        </select>
        <button className="btn" onClick={run}>
          比较（区分数据新增/规则变化/人工决定）
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="compare-result">
          <p className="small muted">
            数据代际：v{result.versions[0]} 第 {result.data_generations[0]} 代 ↔
            v{result.versions[1]} 第 {result.data_generations[1]} 代；
            规则{result.rules_changed ? "已变化" : "未变化"}；
            人工例外集合{result.manual_decisions_changed ? "已变化" : "未变化"}。
          </p>
          {Object.entries(result.attributed_changes).map(([cause, changes]) => (
            <div key={cause}>
              <strong>{CAUSE_LABELS[cause] ?? cause}（{changes.length}）</strong>
              <ul className="affected-list">
                {changes.map((c, i) => (
                  <li key={i} className="small">
                    <code>{c.origins.join(", ")}</code>
                    {c.column ? ` · ${c.column}` : ""} · {c.before ?? "—"} → {c.after}
                  </li>
                ))}
                {changes.length === 0 && <li className="muted small">无</li>}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
