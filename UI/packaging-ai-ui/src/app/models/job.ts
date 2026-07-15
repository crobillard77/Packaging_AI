export type JobStatus =
  | 'queued'
  | 'running'
  | 'awaiting_clarification'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface CreateJobRequest {
  folder_path: string;
  output_dir?: string | null;
  auto_confirm?: boolean;
}

export interface CreateJobResponse {
  id: string;
  status: JobStatus;
  created_at: string;
}

export interface ClarificationNeeded {
  needs_meta: boolean;
  needs_uninstall: boolean;
  needs_soft_confirm: boolean;
  suggested_uninstall: string | null;
  open_questions: string[];
}

export interface PlanSummary {
  app_vendor: string;
  app_name: string;
  app_version: string;
  primary_family: string | null;
  model: string | null;
  reviewer: string | null;
}

export interface JobResponse {
  id: string;
  status: JobStatus;
  folder_path: string;
  output_dir: string | null;
  auto_confirm: boolean;
  confidence_score: number | null;
  review_findings: string[];
  clarification_needed: ClarificationNeeded | null;
  plan_summary: PlanSummary | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ClarifyRequest {
  action?: 'submit' | 'abort';
  meta?: string | null;
  uninstall_command?: string | null;
  uninstall_paste?: string | null;
  confirm?: boolean;
  abort?: boolean;
}

export interface ArtifactsResponse {
  package_dir: string | null;
  deploy_script: string | null;
  logs_dir: string | null;
  install_plan_path: string | null;
  review_path: string | null;
  requirements_path: string | null;
  vulnerability_path: string | null;
  packaging_log_path: string | null;
  footprint_mst_path: string | null;
}

export interface LogFileInfo {
  name: string;
  size_bytes: number;
  modified_at: string | null;
}

export interface LogListResponse {
  logs_dir: string;
  files: LogFileInfo[];
}

export interface LogContentResponse {
  name: string;
  content: string;
  truncated: boolean;
  size_bytes: number;
}
