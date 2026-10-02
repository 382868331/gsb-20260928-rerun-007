export type StepType =
  | "missing_values"
  | "number_check"
  | "unit_convert"
  | "dedup_merge";

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
  structure_actions?: StepAction[];
  adopted_scope?: {
    status: string;
    confirmed_mapping_ids?: string[];
    pending_mappings?: { batch: number; mapping_id: string }[];
  };
  unresolved_mappings?: { batch: number; mapping_id: string }[];
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

export interface MeasurementMapping {
  id: string;
  batch?: number;
  source_columns: string[];
  value_column: string;
  unit_columns: string[];
  representation: string;
  candidate_measurements: string[];
  target_measurement?: string | null;
  target_unit_column?: string | null;
  fixed_unit?: string | null;
  status: string;
  rule_status: string;
  sample_values: Record<string, string>[];
  row_ids?: string[];
}

export interface SchemaBatch {
  batch: number;
  label?: string;
  schema_status: string;
  proposal?: {
    batch: number;
    old_columns: string[];
    new_columns: string[];
    status: string;
    measurements: MeasurementMapping[];
    rule_classification: {
      reusable: string[];
      needs_correspondence: string[];
      conflicting: string[];
    };
  };
  confirmed: MeasurementMapping[];
  confirmed_ids: string[];
  inherited_ids?: string[];
  pending_ids: string[];
}

export interface MappingPlanDiff {
  structure_interpretation: unknown[];
  cleaning_rule_differences: unknown[];
  data_added: string[];
  value_changes: unknown[];
}
