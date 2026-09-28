export type StepReport = {
  step: "missing" | "unit" | "merge";
  changed_rows: number;
  detail: Record<string, unknown>;
};

export type VersionMeta = {
  version: string;
  parent: string | null;
  note: string;
  created_at: string;
  row_count: number;
  reports?: StepReport[];
  pipeline?: PipelineSpec;
};

export type Dataset = {
  id: string;
  name: string;
  created_at: string;
  latest_version: string;
  versions: VersionMeta[];
};

export type DataRow = { sources: string[]; values: Record<string, unknown> };

export type RowsResponse = { version: string; columns: string[]; rows: DataRow[] };

export type PreviewResponse = {
  base_version: string;
  reports: StepReport[];
  preview: {
    rows_before: number;
    rows_after: number;
    before: DataRow[];
    after: DataRow[];
  };
};

export type LineageResponse = {
  dataset_id: string;
  version: string;
  original_record_count: number;
  result_record_count: number;
  rows: { result_row: number; sources: string[] }[];
  versions: VersionMeta[];
};

export type MissingRule = {
  strategy: "mean" | "median" | "constant" | "drop_row";
  column?: string | null;
  fill_value?: number | string | null;
};

export type UnitRule = {
  column: string;
  unit_column: string;
  conversions: Record<string, number>;
  target_unit: string;
};

export type MergeRule = { keys: string[]; conflict: "mean" | "first" | "last" };

export type PipelineSpec = {
  missing?: MissingRule | null;
  unit?: UnitRule | null;
  merge?: MergeRule | null;
};

const JSON_HEADERS = { "Content-Type": "application/json" };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { headers: JSON_HEADERS, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  listDatasets: () => request<{ datasets: Dataset[] }>("/api/datasets"),
  createDataset: (name: string, csv_text: string) =>
    request<Dataset>("/api/datasets", {
      method: "POST",
      body: JSON.stringify({ name, csv_text }),
    }),
  getDataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  getRows: (id: string, version: string) =>
    request<RowsResponse>(`/api/datasets/${id}/versions/${version}/rows`),
  preview: (id: string, base_version: string, pipeline: PipelineSpec) =>
    request<PreviewResponse>(`/api/datasets/${id}/preview`, {
      method: "POST",
      body: JSON.stringify({ base_version, pipeline }),
    }),
  commit: (id: string, base_version: string, note: string, pipeline: PipelineSpec) =>
    request<{ version: VersionMeta }>(`/api/datasets/${id}/versions`, {
      method: "POST",
      body: JSON.stringify({ base_version, note, pipeline }),
    }),
  lineage: (id: string, version: string) =>
    request<LineageResponse>(`/api/datasets/${id}/lineage?version=${encodeURIComponent(version)}`),
};
