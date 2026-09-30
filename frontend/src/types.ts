export type StepType = "missing_values" | "unit_convert" | "dedup_merge";

export interface PipelineStep {
  id: string;
  type: StepType;
  params: Record<string, unknown>;
}

export interface StepStats {
  [key: string]: unknown;
  affected_row_ids?: string[];
  effects?: StepEffect[];
}

export interface StepEffect {
  row_id: string;
  action: "converted" | "filled" | "dropped" | "merged" | "abort";
  detail: Record<string, any>;
}

export interface StepReport {
  type: StepType;
  label: string;
  params: Record<string, unknown>;
  stats: StepStats;
  row_count_before: number;
  row_count_after: number;
}

export interface Row {
  _id: string;
  [key: string]: unknown;
}

export interface PreviewResult {
  reports: StepReport[];
  row_count_before: number;
  row_count_after: number;
  sample: Row[];
  stages: { rows: Row[]; row_count: number; truncated: boolean }[];
}

export interface Treatment {
  step: number;
  type: StepType;
  label: string;
  action: string;
  detail: Record<string, any>;
  origins: string[];
}

export interface VersionMeta {
  version: number;
  created_from: number | null;
  label: string;
  steps: { type: StepType; params: Record<string, unknown> }[];
  reports: StepReport[];
}

export interface Manifest {
  name: string;
  latest_version: number;
  versions: VersionMeta[];
}
