export type StepType =
  | "missing_values"
  | "number_check"
  | "unit_convert"
  | "dedup_merge"
  | "schema_mapping";

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
  row_count_before: number;
  row_count_after: number;
  sample: Row[];
  unmapped_rows?: Row[];
  adopted_scope?: {
    workspace_appended_included: boolean;
    confirmed_mapping_ids: string[];
    published_row_ids: string[];
    note: string;
  };
}

export interface MeasurementMapping {
  id: string;
  batch?: number;
  target_column: string;
  status: string;
  confirmed?: boolean;
  rule_inheritance?: string;
  candidate_columns?: string[];
  value_columns?: string[];
  unit_candidates?: string[];
  unit_column?: string | null;
  unit_mode?: string;
  sample_units?: string[];
  default_unit?: string | null;
  source_column?: string | null;
  sources?: string[];
  reason?: string;
  value_column?: string;
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

export interface SourceRule {
  issue: string;
  action: "error" | "flag" | "drop" | "replace";
  replacement?: number | null;
  value_matches?: string[];
  source_column?: string | null;
  sources?: string[];
  label?: string;
}

export interface ManualException {
  row_id: string;
  scope: string;
  action: "flag" | "drop" | "replace";
  replacement?: number | null;
  reason?: string;
  active?: boolean;
  revoked?: boolean;
}

export interface RuleImpact {
  changed_decisions: {
    row_id: string; column: string; issue: string; issue_label: string;
    original_value: unknown; old_action: string; new_action: string;
    old_replacement?: number | null; new_replacement?: number | null;
    is_new_row?: boolean;
  }[];
  newly_handled: {
    row_id: string; column: string; issue: string; issue_label: string;
    original_value: unknown; action: string; replacement?: number | null;
    rule_label?: string | null; source_column?: string | null;
    source_value?: unknown; is_new_row?: boolean;
  }[];
  conflicting_exceptions: {
    row_id: string; column: string; issue: string;
    manual_action: string; rule_action: string; reason: string;
  }[];
}
