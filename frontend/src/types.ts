export type StepType =
  | "missing_values"
  | "unit_convert"
  | "dedup_merge"
  | "validate_numbers";

export type AnomalyKind = "missing" | "invalid" | "nonfinite";
export type AnomalyAction = "flag" | "drop" | "replace";

export interface AnomalyRule {
  kind: AnomalyKind;
  source?: string;
  action: AnomalyAction;
  value?: string | number;
}

export interface AnomalyMarker {
  kind: AnomalyKind;
  raw: unknown;
  stage: string;
  unit?: string;
}

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
  actions?: StepAction[];
}

export interface StepAction {
  origins: string[];
  description: string;
  detail: Record<string, unknown>;
}

export interface Row {
  _id: string;
  [key: string]: unknown;
}

export interface PreviewResult {
  reports: StepReport[];
  base_version?: number;
  row_count_before: number;
  row_count_after: number;
  sample: Row[];
  anomalies?: Record<string, Record<string, AnomalyMarker>>;
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
