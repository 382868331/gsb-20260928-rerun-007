import type { Manifest, PipelineStep, PreviewResult, Row, StepReport } from "./types";

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
    request<{
      manifest: Manifest; columns: string[]; row_count: number;
      exceptions?: Record<string, import("./types").ManualException>;
      appended?: { _id: string; batch: number; label?: string }[];
    }>(
      `/api/projects/${encodeURIComponent(name)}`
    ),

  getVersion: (name: string, version: number) =>
    request<{ version: number; rows: Row[]; columns: string[]; step_reports: StepReport[] }>(
      `/api/projects/${encodeURIComponent(name)}/versions/${version}`
    ),

  preview: (name: string, steps: PipelineStep[], sourceVersion?: number,
    opts?: { includeAppended?: boolean; useExceptions?: boolean }) =>
    request<PreviewResult>(`/api/projects/${encodeURIComponent(name)}/preview`, {
      method: "POST",
      body: JSON.stringify({
        source_version: sourceVersion,
        include_appended: opts?.includeAppended ?? false,
        use_exceptions: opts?.useExceptions ?? true,
        steps: steps.map(({ type, params }) => ({ type, params })),
      }),
    }),

  apply: (name: string, label: string, steps: PipelineStep[], sourceVersion?: number,
    opts?: { includeAppended?: boolean; useExceptions?: boolean }) =>
    request<{ version: number; reports: StepReport[] }>(
      `/api/projects/${encodeURIComponent(name)}/apply`,
      {
        method: "POST",
        body: JSON.stringify({
          label,
          source_version: sourceVersion,
          include_appended: opts?.includeAppended ?? false,
          use_exceptions: opts?.useExceptions ?? true,
          steps: steps.map(({ type, params }) => ({ type, params })),
        }),
      }
    ),

  lineage: (name: string, version: number, rowId: string) =>
    request<{ row_id: string; origins: string[]; origin_rows: Row[]; timeline: { step: string; description: string }[] }>(
      `/api/projects/${encodeURIComponent(name)}/versions/${version}/lineage/${rowId}`
    ),

  appendBatch: (name: string, csv: string, label: string) =>
    request<{ ok: boolean; batch: number; new_ids: string[]; new_rows: Row[] }>(
      `/api/projects/${encodeURIComponent(name)}/batches/append`,
      { method: "POST", body: JSON.stringify({ csv, label }) },
    ),

  setException: (name: string, payload: {
    row_id: string; scope: string; action: string;
    replacement?: number | null; reason?: string;
  }) =>
    request<{ ok: boolean }>(
      `/api/projects/${encodeURIComponent(name)}/exceptions/set`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  revokeException: (name: string, rowId: string, scope: string) =>
    request<{ ok: boolean }>(
      `/api/projects/${encodeURIComponent(name)}/exceptions/revoke`,
      { method: "POST", body: JSON.stringify({ row_id: rowId, scope }) },
    ),

  ruleImpact: (name: string, payload: {
    step_type: string; columns?: string[];
    old_params: Record<string, unknown>; new_params: Record<string, unknown>;
  }) =>
    request<{
      changed_decisions: unknown[]; newly_handled: unknown[];
      conflicting_exceptions: unknown[];
    }>(`/api/projects/${encodeURIComponent(name)}/rule-impact`, {
      method: "POST", body: JSON.stringify(payload),
    }),

  diffVersions: (name: string, versionA: number, versionB: number) =>
    request<Record<string, unknown[]>>(
      `/api/projects/${encodeURIComponent(name)}/diff`,
      { method: "POST",
        body: JSON.stringify({ version_a: versionA, version_b: versionB }) },
    ),
};
