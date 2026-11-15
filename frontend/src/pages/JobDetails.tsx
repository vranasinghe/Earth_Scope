import { ArrowLeft, CheckCircle2, Circle, Download, Loader2, RotateCcw, XCircle } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { DataModeBadge } from '../components/common/DataModeBadge'
import { SectionHeading } from '../components/common/SectionHeading'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { Counters, JobProgressBar, JobStatusBadge } from '../components/jobs/JobParts'
import { confirmCancel, variableLabel } from '../utils/jobs'
import { useAiPageContext } from '../context/aiChatContext'
import { useJob, useJobSession } from '../hooks/useJobs'
import { jobDetailsContext } from '../utils/buildAiContext'
import { ApiError, jobsApi } from '../services/api'
import type { Job, StageInfo } from '../types/jobs'
import { formatDateTime } from '../utils/format'
import { isJobId, jobResultsPath } from '../utils/region'

const EXPORTS = [
  ['exports/annual.csv', 'Annual series (CSV)'],
  ['exports/monthly.csv', 'Monthly series (CSV)'],
  ['exports/spatial_cells.csv', 'Per-cell trends (CSV)'],
  ['exports/provenance.json', 'Provenance & request manifest (JSON)'],
] as const

export default function JobDetails() {
  const { jobId = '' } = useParams()
  const valid = isJobId(jobId)
  const sessionError = useJobSession()
  const { data: job, error, loading, refresh } = useJob(valid ? jobId : null)
  useAiPageContext(
    job ? jobDetailsContext(job.job_id, `Background job: ${job.area.name ?? job.area.iso3 ?? 'area'} (${job.status})`, job.status === 'COMPLETED') : null,
  )

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <Link to="/jobs" className="btn-ghost -ml-3 mb-6">
        <ArrowLeft className="size-4" aria-hidden /> All analysis jobs
      </Link>
      {!valid && <Notice tone="warn">This job link is not valid.</Notice>}
      {sessionError && <ErrorState error={sessionError} title="Could not start an analysis session" />}
      {valid && loading && !job && <LoadingState title="Loading the job status…" />}
      {valid && error && !job && (
        <ErrorState
          error={error}
          title={error.status === 404 ? 'This job does not exist for this browser session' : 'Could not load this job'}
          onRetry={error.status === 404 ? undefined : refresh}
        >
          {error.status === 404 && (
            <p className="text-sm text-fg-muted">Jobs are private to the browser that submitted them. Open the link in that browser.</p>
          )}
        </ErrorState>
      )}
      {job && <Details job={job} stale={!!error} onChanged={refresh} />}
    </div>
  )
}

function Details({ job, stale, onChanged }: { job: Job; stale: boolean; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<ApiError | null>(null)
  const [retryNote, setRetryNote] = useState<string | null>(null)
  const p = job.progress

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setActionError(null)
    try {
      await fn()
    } catch (err) {
      setActionError(err instanceof ApiError ? err : new ApiError(0, {}, 'The action failed.'))
    } finally {
      setBusy(false)
      onChanged()
    }
  }
  const cancel = () => {
    if (confirmCancel(job)) void run(async () => void (await jobsApi.cancel(job.job_id)))
  }
  const retry = () =>
    void run(async () => {
      const r = await jobsApi.retry(job.job_id)
      setRetryNote(
        `Retry queued. ${r.resumable.verified_tiles} of ${r.resumable.tiles_total} NASA tiles are already verified and will not be downloaded again.`,
      )
    })

  return (
    <div className="space-y-10">
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">
            {job.area.name}
            {job.area.iso3 ? <span className="text-fg-muted"> ({job.area.iso3})</span> : null}
          </h1>
          <JobStatusBadge status={job.status} />
          <DataModeBadge mode={job.data_mode} size="lg" />
        </div>
        <p className="mt-2 text-fg-muted">
          {job.area.kind === 'country' ? 'Country' : 'Polygon'} · {variableLabel(job)} · {job.start_year}–{job.end_year} · {job.tier.toLowerCase().replace('_', ' ')} job
        </p>
      </header>

      {stale && <Notice tone="warn">Connection problem — showing the last known state; retrying automatically.</Notice>}
      {actionError && <ErrorState error={actionError} title="The action could not be completed" />}
      {retryNote && <Notice tone="info">{retryNote}</Notice>}

      <section aria-labelledby="progress-h" className="card card-pad space-y-5">
        <h2 id="progress-h" className="text-xl font-semibold">Progress</h2>
        <JobProgressBar progress={p} label="Overall analysis progress" />
        {p.activity && <p className="text-sm text-fg-muted" aria-live="polite">{p.activity}</p>}
        <Counters progress={p} />
        <StageList stages={p.stages} />
        <p className="text-xs text-fg-subtle">
          The percentage is computed by the server from completed work (tiles verified, cells analysed) and documented stage weights.
          It reaches 100% only after the results are verified and stored. Last update {p.updated_at ? formatDateTime(p.updated_at) : '—'} ·
          attempts {p.attempts.total}
          {p.attempts.manual_retries ? ` · ${p.attempts.manual_retries} manual retr${p.attempts.manual_retries === 1 ? 'y' : 'ies'}` : ''}
        </p>
      </section>

      {job.error && job.status !== 'COMPLETED' && (
        <div className={`card card-pad ${job.status === 'FAILED' ? 'border-danger/40' : 'border-warn/40'}`} role="alert">
          <p className="font-semibold">
            {job.status === 'FAILED' ? 'The analysis failed' : 'A temporary problem occurred — the job retries automatically'}
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            <span className="font-mono">{job.error.code}</span>: {job.error.message}
          </p>
          {job.status === 'FAILED' && !job.can_retry && (
            <p className="mt-2 text-sm text-fg-muted">This failure comes from the request itself, so retrying cannot help. Please start a new analysis.</p>
          )}
        </div>
      )}

      <section aria-labelledby="actions-h">
        <SectionHeading id="actions-h" title="Actions" />
        <div className="flex flex-wrap gap-3">
          {job.status === 'COMPLETED' && (
            <Link to={jobResultsPath(job.job_id)} className="btn-primary">
              View results
            </Link>
          )}
          {job.can_retry && (
            <button type="button" className="btn-secondary" onClick={retry} disabled={busy}>
              <RotateCcw className="size-4" aria-hidden /> Retry analysis
            </button>
          )}
          {job.can_cancel && (
            <button type="button" className="btn-secondary text-danger" onClick={cancel} disabled={busy}>
              Cancel analysis
            </button>
          )}
          {job.status === 'EXPIRED' && <p className="text-sm text-fg-muted">The results were deleted after the retention period. Run the analysis again.</p>}
        </div>
        {job.status === 'COMPLETED' && (
          <div className="mt-4 flex flex-wrap gap-2">
            {EXPORTS.map(([name, label]) => (
              <a key={name} className="btn-ghost" href={jobsApi.artifactUrl(job.job_id, name)} download>
                <Download className="size-4" aria-hidden /> {label}
              </a>
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="details-h">
        <SectionHeading id="details-h" title="Details" />
        <dl className="card card-pad grid grid-cols-1 gap-x-6 gap-y-4 min-[420px]:grid-cols-2 lg:grid-cols-3">
          <Item label="Variable" value={variableLabel(job)} />
          <Item label="NASA community" value={job.community} />
          <Item label="Period" value={`${job.start_year} – ${job.end_year} · monthly`} />
          <Item label="Data source" value={job.dataset_version} />
          <Item label="Boundary" value={job.area.kind === 'country' ? `${job.area.boundary_source ?? '—'} · ${job.area.boundary_version ?? '—'}` : 'Custom polygon'} />
          <Item label="Geometry id" value={<span className="font-mono text-xs">{job.area.geometry_id}</span>} />
          <Item label="NASA requests" value={String(job.preflight.n_tiles ?? job.progress.download.tiles_total)} />
          <Item label="Grid cells" value={(job.preflight.n_cells ?? job.progress.processing.cells_total).toLocaleString()} />
          <Item label="Submitted" value={job.created_at ? formatDateTime(job.created_at) : '—'} />
          <Item label="Started" value={job.started_at ? formatDateTime(job.started_at) : '—'} />
          <Item label="Completed" value={job.completed_at ? formatDateTime(job.completed_at) : '—'} />
          <Item label="Results kept until" value={job.expires_at ? formatDateTime(job.expires_at) : '—'} />
          <Item label="Software" value={job.software_version} />
          <Item label="Configuration hash" value={<span className="font-mono text-xs">{job.config_hash.slice(0, 16)}…</span>} />
        </dl>
      </section>

      {job.events.length > 0 && (
        <section aria-labelledby="events-h">
          <SectionHeading id="events-h" title="Processing log" description="Retries, recoveries and failures recorded by the workers." />
          <ol className="card card-pad space-y-2 text-sm">
            {job.events.map((e, i) => (
              <li key={`${e.at}-${i}`} className="flex gap-3">
                <span className="stat-num shrink-0 text-xs text-fg-subtle">{e.at ? formatDateTime(e.at) : ''}</span>
                <span className={e.level === 'error' ? 'text-danger' : e.level === 'warn' ? 'text-warn' : 'text-fg-muted'}>{e.message}</span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  )
}

function StageList({ stages }: { stages: StageInfo[] }) {
  return (
    <ol className="grid gap-1.5 text-sm sm:grid-cols-2" aria-label="Processing stages">
      {stages.map((s) => {
        const Icon = s.state === 'done' ? CheckCircle2 : s.state === 'current' ? Loader2 : s.state === 'failed' || s.state === 'cancelled' ? XCircle : Circle
        const tone = s.state === 'done' ? 'text-teal' : s.state === 'current' ? 'text-accent' : s.state === 'failed' ? 'text-danger' : 'text-fg-subtle'
        return (
          <li key={s.id} className="flex items-center gap-2">
            <Icon className={`size-4 shrink-0 ${tone} ${s.state === 'current' ? 'animate-spin' : ''}`} aria-hidden />
            <span className={s.state === 'pending' ? 'text-fg-subtle' : 'text-fg'}>
              {s.label}
              <span className="sr-only"> — {s.state}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm font-semibold text-fg-subtle">{label}</dt>
      <dd className="mt-1 break-words text-sm text-fg">{value}</dd>
    </div>
  )
}
