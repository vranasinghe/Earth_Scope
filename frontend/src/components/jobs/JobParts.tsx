import { AlertTriangle, CheckCircle2, Clock, Loader2, RotateCcw, Square, XCircle } from 'lucide-react'
import { Link } from 'react-router'
import type { Job, JobProgress, JobStatus } from '../../types/jobs'
import { formatDateTime } from '../../utils/format'
import { STATUS_TEXT, variableLabel } from '../../utils/jobs'
import { jobResultsPath } from '../../utils/region'
import { DataModeBadge } from '../common/DataModeBadge'


const TONE: Record<JobStatus, string> = {
  PENDING: 'border-line-strong text-fg-muted',
  QUEUED: 'border-line-strong text-fg-muted',
  RUNNING: 'border-accent/50 bg-accent/10 text-accent',
  RETRYING: 'border-warn/50 bg-warn/10 text-warn',
  CANCEL_REQUESTED: 'border-warn/50 bg-warn/10 text-warn',
  CANCELLED: 'border-line-strong text-fg-subtle',
  COMPLETED: 'border-teal/50 bg-teal/10 text-teal',
  FAILED: 'border-danger/50 bg-danger/10 text-danger',
  EXPIRED: 'border-line-strong text-fg-subtle',
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const Icon =
    status === 'COMPLETED' ? CheckCircle2 : status === 'FAILED' ? XCircle : status === 'RUNNING' ? Loader2
      : status === 'CANCELLED' || status === 'EXPIRED' ? Square : status === 'RETRYING' ? RotateCcw : status === 'CANCEL_REQUESTED' ? AlertTriangle : Clock
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${TONE[status]}`}>
      <Icon className={`size-3.5 ${status === 'RUNNING' ? 'animate-spin' : ''}`} aria-hidden />
      {STATUS_TEXT[status]}
    </span>
  )
}

/** Overall progress from the backend's stage-weighted work counters (never a timer). */
export function JobProgressBar({ progress, label }: { progress: JobProgress; label: string }) {
  const pct = Math.max(0, Math.min(100, progress.progress_pct))
  const done = progress.status === 'COMPLETED'
  const failed = progress.status === 'FAILED' || progress.status === 'CANCELLED' || progress.status === 'EXPIRED'
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
        <span className="min-w-0 truncate text-fg-muted">{progress.stage_label}</span>
        <span className="stat-num shrink-0 text-fg">{pct.toFixed(0)}%</span>
      </div>
      <div
        className="h-2.5 overflow-hidden rounded-full bg-raised"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-valuetext={`${pct.toFixed(0)}% — ${progress.stage_label}`}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${done ? 'bg-teal' : failed ? 'bg-line-strong' : 'bg-accent'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export function Counters({ progress }: { progress: JobProgress }) {
  const d = progress.download
  const p = progress.processing
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm">
      <div>
        <dt className="text-sm text-fg-subtle">NASA tiles</dt>
        <dd className="stat-num text-fg">
          {d.tiles_completed} / {d.tiles_total}
          {d.tiles_retrying > 0 && <span className="ml-1 text-warn">({d.tiles_retrying} retrying)</span>}
          {d.tiles_failed > 0 && <span className="ml-1 text-danger">({d.tiles_failed} failed)</span>}
        </dd>
      </div>
      <div>
        <dt className="text-sm text-fg-subtle">Grid cells analysed</dt>
        <dd className="stat-num text-fg">
          {p.cells_processed.toLocaleString()} / {p.cells_total.toLocaleString()}
        </dd>
      </div>
    </dl>
  )
}


export interface JobActions {
  onCancel?: (j: Job) => void
  onRetry?: (j: Job) => void
  busy?: boolean
}

export function JobCard({ job, onCancel, onRetry, busy }: { job: Job } & JobActions) {
  return (
    <article className="card card-pad flex flex-col gap-4" aria-labelledby={`job-${job.job_id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={`job-${job.job_id}`} className="truncate text-lg font-semibold">
            {job.area.name}
            {job.area.iso3 ? <span className="ml-1 text-fg-muted">({job.area.iso3})</span> : null}
          </h3>
          <p className="text-sm text-fg-muted">
            {variableLabel(job)} · {job.start_year}–{job.end_year}
          </p>
          <p className="text-xs text-fg-subtle">Submitted {job.created_at ? formatDateTime(job.created_at) : '—'}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DataModeBadge mode={job.data_mode} />
          <JobStatusBadge status={job.status} />
        </div>
      </div>
      <JobProgressBar progress={job.progress} label={`Progress of ${job.area.name}`} />
      {job.status !== 'COMPLETED' && <Counters progress={job.progress} />}
      {job.error && job.status === 'FAILED' && (
        <p className="text-sm text-danger">
          {job.error.code}: {job.error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Link to={`/jobs/${job.job_id}`} className="btn-secondary">
          View details
        </Link>
        {job.status === 'COMPLETED' && (
          <Link to={jobResultsPath(job.job_id)} className="btn-primary">
            View results
          </Link>
        )}
        {job.can_retry && onRetry && (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => onRetry(job)}>
            <RotateCcw className="size-4" aria-hidden /> Retry
          </button>
        )}
        {job.can_cancel && onCancel && (
          <button type="button" className="btn-ghost text-danger" disabled={busy} onClick={() => onCancel(job)}>
            Cancel
          </button>
        )}
      </div>
    </article>
  )
}
