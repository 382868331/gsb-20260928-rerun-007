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
  old_record_count?: number;
  new_record_count?: number;
  new_row_ids?: string[];
  conflicts?: RuleConflict[];
}

export interface RuleConflict {
  id: string;
  row_id: string;
  column: string;
  issue: string;
  manual_action: string;
  current_rule_fingerprint: string;
  saved_rule_fingerprint: string;
}

export interface ManualException {
  id: string;
  row_id: string;
  column: string;
  issue: string;
  stage?: string | null;
  action: string;
  replacement?: number | null;
  reason?: string;
  status: string;
  rule_fingerprint: string;
}

export interface ExceptionStore {
  next_id: number;
  decisions: ManualException[];
}

export interface VersionComparison {
  versions: number[];
  data_generations: number[];
  rules_changed: boolean;
  manual_decisions_changed: boolean;
  data_added_origins: string[];
  data_removed_origins: string[];
  attributed_changes: {
    data_added: { origins: string[]; column: string | null; before: string | null; after: string; cause: string }[];
    rule_changed: { origins: string[]; column: string | null; before: string; after: string; cause: string }[];
    manual_decision: { origins: string[]; column: string | null; before: string; after: string; cause: string }[];
  };
  manual_exception_ids: { a: string[]; b: string[] };
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
  working_generation?: number;
  batches?: { generation: number; label: string; row_ids: string[]; row_count: number }[];
  versions: VersionMeta[];
}
