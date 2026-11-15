// TypeScript mirror of backend/app/models/job_schemas.py (background analysis jobs).

import type { DataMode } from './api'
import type { AreaDescription, AreaRef, Preflight } from './area'

export type JobStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRYING'
  | 'CANCEL_REQUESTED'
  | 'CANCELLED'
  | 'COMPLETED'
  | 'FAILED'
  | 'EXPIRED'

export const ACTIVE_STATUSES: ReadonlySet<JobStatus> = new Set(['PENDING', 'QUEUED', 'RUNNING', 'RETRYING', 'CANCEL_REQUESTED'])

export type ResourceTier = 'SMALL' | 'MEDIUM' | 'LARGE' | 'VERY_LARGE' | 'BLOCKED'

export interface StageInfo {
  id: string
  label: string
  description?: string | null
  state?: 'done' | 'current' | 'pending' | 'failed' | 'cancelled' | null
}

export interface JobProgress {
  job_id: string
  status: JobStatus
  stage: string
  stage_label: string
  activity: string | null
  progress_pct: number
  is_active: boolean
  download: { tiles_completed: number; tiles_total: number; tiles_retrying: number; tiles_failed: number }
  processing: { cells_processed: number; cells_total: number }
  attempts: { total: number; automatic: number; max_automatic: number | null; manual_retries: number }
  updated_at: string | null
  heartbeat_at: string | null
  stages: StageInfo[]
}

export interface JobEvent {
  at: string | null
  level: 'info' | 'warn' | 'error' | string
  stage: string | null
  message: string
}

export interface Job {
  job_id: string
  job_type: string
  status: JobStatus
  tier: ResourceTier
  data_mode: DataMode
  area: { kind: 'country' | 'polygon'; name: string; iso3: string | null; geometry_id: string; boundary_source: string | null; boundary_version: string | null }
  variable_id: string
  parameter: string
  community: string
  start_year: number
  end_year: number
  config: Record<string, unknown>
  config_hash: string
  preflight: { n_cells?: number; n_tiles?: number; n_months?: number; n_values?: number; grid?: string; estimates?: BackgroundEstimate }
  progress: JobProgress
  error: { code: string; message: string | null; retryable: boolean } | null
  created_at: string | null
  queued_at: string | null
  started_at: string | null
  updated_at: string | null
  completed_at: string | null
  expires_at: string | null
  software_version: string
  dataset_version: string
  can_cancel: boolean
  can_retry: boolean
  has_results: boolean
  links: Record<string, string>
  events: JobEvent[]
}

export interface BackgroundEstimate {
  basis: string
  download_seconds: number
  processing_seconds: number
  total_seconds: number
  memory_mb: number
  storage_mb: number
  note: string
}

export interface BackgroundPreflight {
  tier: ResourceTier
  eligible: boolean
  synchronous_available: boolean
  reasons: string[]
  estimates: BackgroundEstimate | null
  stages: StageInfo[]
  limits: Record<string, unknown>
  config_hash: string | null
}

export interface JobPreflightResponse {
  area: AreaDescription
  preflight: Preflight
  background: BackgroundPreflight
  variable: string
  start_year: number
  end_year: number
  data_mode: DataMode
}

export interface JobSubmitResponse {
  job_id: string
  status: JobStatus
  created: boolean
  duplicate_of_reason: 'idempotency_key' | 'active_duplicate' | 'completed_duplicate' | null
  status_url: string
  created_at: string | null
  accepted_configuration: Record<string, unknown>
  job: Job
}

export interface JobRequestParams {
  area: AreaRef
  variable: string
  startYear: number
  endYear: number
  coverageThreshold: number
  method?: string
  correction?: string
  alpha?: number
}

export interface RetryResponse {
  job: Job
  resumable: { verified_tiles: number; tiles_total: number; checkpoints: string[]; statistics_chunks_done: number }
}
