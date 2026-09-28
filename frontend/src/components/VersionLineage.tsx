import { useEffect, useState } from "react";
import { api, Dataset, LineageResponse } from "../types";

export function VersionLineage({ datasetId, dataset }: { datasetId: string; dataset: Dataset }) {
  const [selected, setSelected] = useState(dataset.latest_version);
  const [lineage, setLineage] = useState<LineageResponse | null>(null);

  useEffect(() => {
    setSelected(dataset.latest_version);
  }, [dataset.latest_version]);

  useEffect(() => {
    api.lineage(datasetId, selected).then(setLineage).catch(() => setLineage(null));
  }, [datasetId, selected]);

  return (
    <section className="card">
      <h2>4. 版本与血缘</h2>
      <p className="hint">重开工程仍可查看历史版本；点击结果行可追溯到 v1 原件中的记录 ID。</p>
      <div className="version-chain">
        {dataset.versions.map((item, index) => (
          <button
            key={item.version}
            className={item.version === selected ? "version active" : "version"}
            onClick={() => setSelected(item.version)}
          >
            {item.version}
            <small>{item.row_count} 行{index > 0 ? ` · 基于 ${item.parent}` : " · 原件"}</small>
          </button>
        ))}
      </div>
      {lineage && (
        <div>
          <p>
            原件 <strong>{lineage.original_record_count}</strong> 条 → 当前版本
            <strong> {lineage.result_record_count}</strong> 条
          </p>
          <div className="lineage-grid">
            {lineage.rows.map((row) => (
              <div key={row.result_row} className="lineage-row">
                <span className="result-id">结果第 {row.result_row} 行</span>
                <span className="arrow">←</span>
                <span className="source-ids">{row.sources.join(", ")}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
