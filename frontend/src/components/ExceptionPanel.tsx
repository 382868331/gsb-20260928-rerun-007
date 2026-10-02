import { useEffect, useState } from "react";
import { UserCog } from "lucide-react";
import type { ExceptionStore, ManualException } from "../types";

export function ExceptionPanel({
  project,
  listExceptions,
  withdrawException,
  changed,
}: {
  project: string;
  listExceptions: () => Promise<ExceptionStore>;
  withdrawException: (id: string) => Promise<unknown>;
  changed: number;
}) {
  const [store, setStore] = useState<ExceptionStore | null>(null);
  const [busyId, setBusyId] = useState("");

  useEffect(() => {
    listExceptions().then(setStore).catch(() => setStore(null));
  }, [project, changed]);

  if (!store || store.decisions.length === 0) return null;

  async function withdraw(id: string) {
    setBusyId(id);
    try {
      await withdrawException(id);
      setStore(await listExceptions());
    } finally {
      setBusyId("");
    }
  }

  const statusLabel: Record<string, string> = {
    active: "生效中",
    withdrawn: "已撤回",
    withdrawn_conflict: "冲突后撤回",
    superseded: "已被新决定替代",
  };

  return (
    <section className="card">
      <h2>
        <UserCog size={16} /> 人工例外（逐条可追溯，撤回后恢复规则决定）
      </h2>
      <table className="rules-table">
        <thead>
          <tr>
            <th>编号</th><th>记录</th><th>列/异常</th><th>人工决定</th>
            <th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {store.decisions.map((d: ManualException) => (
            <tr key={d.id} className={d.status === "active" ? "" : "muted-row"}>
              <td className="mono">{d.id}</td>
              <td className="mono">{d.row_id}</td>
              <td>{d.column} · {d.issue}{d.replacement != null ? ` → ${d.replacement}` : ""}</td>
              <td>{actionText(d.action)}</td>
              <td>{statusLabel[d.status] ?? d.status}</td>
              <td>
                {d.status === "active" && (
                  <button
                    className="btn small"
                    disabled={busyId === d.id}
                    onClick={() => withdraw(d.id)}
                  >
                    撤回
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function actionText(action: string) {
  if (action === "drop") return "排除该行";
  if (action === "flag") return "保留待核对";
  if (action === "replace") return "使用替代值";
  return action;
}
