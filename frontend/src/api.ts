import type {
  ExceptionStore,
  Manifest,
  ManualException,
  PipelineStep,
  PreviewResult,
  Row,
  StepReport,
  VersionComparison,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
  return body as T;
}

export const api = {
  listProjects: () => request<{ projects: string[] }>("/api/projects"),

  createProject: (name: string, csv: string) =>
    request<{ ok: boolean }>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, csv }),
    }),

  getProject: (name: string) =>
    request<{ manifest: Manifest; columns: string[]; row_count: number }>(
      `/api/projects/${encodeURIComponent(name)}`
    ),

  getVersion: (name: string, version: number) =>
    request<{ version: number; rows: Row[]; columns: string[]; step_reports: StepReport[] }>(
      `/api/projects/${encodeURIComponent(name)}/versions/${version}`
    ),

  preview: (name: string, steps: PipelineStep[], sourceVersion?: number) =>
    request<PreviewResult>(`/api/projects/${encodeURIComponent(name)}/preview`, {
      method: "POST",
      body: JSON.stringify({
        source_version: sourceVersion,
        steps: steps.map(({ type, params }) => ({ type, params })),
      }),
    }),

  apply: (
    name: string,
    label: string,
    steps: PipelineStep[],
    sourceVersion?: number,
    conflictResolutions?: Record<string, "keep" | "withdraw">,
  ) =>
    request<{ version: number; reports: StepReport[] }>(
      `/api/projects/${encodeURIComponent(name)}/apply`,
      {
        method: "POST",
        body: JSON.stringify({
          label,
          source_version: sourceVersion,
          conflict_resolutions: conflictResolutions,
          steps: steps.map(({ type, params }) => ({ type, params })),
        }),
      }
    ),

  lineage: (name: string, version: number, rowId: string) =>
    request<{ row_id: string; origins: string[]; origin_rows: Row[]; timeline: { step: string; description: string }[] }>(
      `/api/projects/${encodeURIComponent(name)}/versions/${version}/lineage/${rowId}`
    ),

  appendBatch: (name: string, csv: string, label?: string) =>
    request<{
      generation: number;
      batch: { generation: number; label: string; row_ids: string[]; row_count: number };
      new_rows: Row[];
      old_record_count: number;
    }>(`/api/projects/${encodeURIComponent(name)}/batches`, {
      method: "POST",
      body: JSON.stringify({ csv, label }),
    }),

  listExceptions: (name: string, version = 0) =>
    request<ExceptionStore>(
      `/api/projects/${encodeURIComponent(name)}/versions/${version}/exceptions`
    ),

  saveException: (
    name: string,
    exception: {
      steps: { type: string; params: Record<string, unknown> }[];
      row_id: string;
      column: string;
      issue: string;
      stage?: string;
      action: string;
      replacement?: number;
      reason?: string;
    },
  ) =>
    request<{ exception: ManualException }>(
      `/api/projects/${encodeURIComponent(name)}/exceptions`,
      {
        method: "POST",
        body: JSON.stringify(exception),
      }
    ),

  withdrawException: (name: string, id: string) =>
    request<{ exception: ManualException }>(
      `/api/projects/${encodeURIComponent(name)}/exceptions/${encodeURIComponent(id)}/withdraw`,
      { method: "POST" },
    ),

  compareVersions: (name: string, a: number, b: number) =>
    request<VersionComparison>(
      `/api/projects/${encodeURIComponent(name)}/compare/${a}/${b}`,
      { method: "POST", body: "{}" },
    ),
};
