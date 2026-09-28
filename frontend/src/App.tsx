import { useEffect, useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { RulePanel } from "./components/RulePanel";
import { PreviewPanel } from "./components/PreviewPanel";
import { VersionLineage } from "./components/VersionLineage";
import { DataTable } from "./components/DataTable";
import { api, Dataset, PipelineSpec, RowsResponse } from "./types";

const EMPTY_SPEC: PipelineSpec = { missing: null, unit: null, merge: null };

export default function App() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [rows, setRows] = useState<RowsResponse | null>(null);
  const [spec, setSpec] = useState<PipelineSpec>(EMPTY_SPEC);

  const refreshDatasets = async () => {
    const result = await api.listDatasets();
    setDatasets(result.datasets);
  };

  const openDataset = async (id: string) => {
    const detail = await api.getDataset(id);
    setDataset(detail);
  };

  useEffect(() => {
    refreshDatasets();
  }, []);

  useEffect(() => {
    if (!dataset) return;
    api.getRows(dataset.id, dataset.latest_version).then(setRows);
  }, [dataset]);

  const reloadAfterCommit = async () => {
    if (!dataset) return;
    await refreshDatasets();
    const detail = await api.getDataset(dataset.id);
    setDataset(detail);
    setSpec(EMPTY_SPEC);
  };

  return (
    <div className="app">
      <header>
        <h1>实验数据清洗工作台</h1>
        <p>原件不可变 · 规则生成新版本 · 每条结果可追溯原记录 · 失败不发布半成品</p>
      </header>

      {datasets.length > 0 && (
        <div className="dataset-switch">
          已有数据集：
          {datasets.map((item) => (
            <button key={item.id} className={dataset?.id === item.id ? "active" : ""} onClick={() => openDataset(item.id)}>
              {item.name}（{item.latest_version}）
            </button>
          ))}
        </div>
      )}

      {!dataset ? (
        <UploadPanel onCreated={openDataset} />
      ) : (
        <main>
          <section className="card">
            <h2>{dataset.name} <small>{dataset.id}</small></h2>
            <p className="hint">当前版本 {dataset.latest_version} 的数据（原件保留，不会被修改）</p>
            {rows && <DataTable columns={rows.columns} rows={rows.rows} />}
          </section>
          <RulePanel columns={rows?.columns ?? []} spec={spec} onChange={setSpec} />
          <PreviewPanel
            datasetId={dataset.id}
            baseVersion={dataset.latest_version}
            columns={rows?.columns ?? []}
            spec={spec}
            onCommitted={reloadAfterCommit}
          />
          <VersionLineage datasetId={dataset.id} dataset={dataset} />
        </main>
      )}
    </div>
  );
}
