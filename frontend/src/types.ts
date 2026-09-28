export type StepType = "missing_values" | "unit_convert" | "dedup_merge";

export interface PipelineStep {
  id: string;
  type: StepType;
  params: Record<string, unknown>;
}

export interface StepStats {
  [key: string]: unknown;
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
