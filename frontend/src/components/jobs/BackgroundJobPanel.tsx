import { CheckCircle2, Clock, Loader2, Server } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiError, jobsApi } from '../../services/api'
import type { JobPreflightResponse, JobRequestParams } from '../../types/jobs'
import { ErrorState } from '../common/States'

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function minutes(s: number): string {
  if (s < 90) return `~${Math.max(1, Math.round(s))} s`
  return `~${Math.round(s / 60)} min`
}

const TIER_TEXT: Record<string, string> = {
  SMALL: 'Small — also fits the instant (synchronous) analysis',
  MEDIUM: 'Medium — runs on a background worker',
  LARGE: 'Large — background worker, chunked processing with checkpoints',
  VERY_LARGE: 'Very large — exceeds this deployment’s background budget',
  BLOCKED: 'Not analysable',
}

/**
 * "Preview Analysis" → backend preflight (no NASA call) → "Start Background Analysis".
 * One idempotency key per preview: a double click re-sends the same key and the
 * backend returns the job it already created instead of starting a second one.
 */
export function BackgroundJobPanel({ params, disabledReason }: { params: JobRequestParams | null; disabledReason: string | null }) {
  const navigate = useNavigate()
  const [preview, setPreview] = useState<JobPreflightResponse | null>(null)
  const [previewKey, setPreviewKey] = useState<string | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [state, setState] = useState<'idle' | 'checking' | 'submitting'>('idle')
  const idem = useRef<string>(newKey())
  const paramsKey = useMemo(() => (params ? JSON.stringify(params) : null), [params])
  const current = preview && previewKey === paramsKey ? preview : null

  const check = async () => {
    if (!params) return
    setState('checking')
    setError(null)
    try {
      const r = await jobsApi.preflight(params)
      setPreview(r)
      setPreviewKey(paramsKey)
      idem.current = newKey()
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, {}, 'The preflight check failed.'))
    } finally {
      setState('idle')
    }
  }

  const start = async () => {
    if (!params || state !== 'idle') return
    setState('submitting')
    setError(null)
    try {
      const r = await jobsApi.submit(params, idem.current)
      navigate(`/jobs/${r.job_id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, {}, 'The analysis could not be submitted.'))
      setState('idle')
    }
  }

  const b = current?.background
  return (
    <section className="panel space-y-4 p-5" aria-labelledby="bg-job-h">
      <div className="flex items-start gap-3">
        <Server className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
        <div>
          <h3 id="bg-job-h" className="font-bold">Background analysis</h3>
          <p className="text-sm text-fg-muted">
            For large countries and polygons: the analysis runs on a server worker, survives page reloads, and you can come back for the
            results later on the Analysis Jobs page.
          </p>
        </div>
      </div>

      {disabledReason ? (
        <p className="text-sm text-fg-subtle">{disabledReason}</p>
      ) : (
        <button type="button" className="btn-secondary" onClick={check} disabled={!params || state !== 'idle'}>
          {state === 'checking' ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Clock className="size-4" aria-hidden />}
          Preview analysis requirements
        </button>
      )}

      {error && <ErrorState error={error} title="Background analysis unavailable" />}

      {current && b && (
        <div className="space-y-3" aria-live="polite">
          <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm min-[420px]:grid-cols-2">
            <div>
              <dt className="text-sm text-fg-subtle">Resource tier</dt>
              <dd>{TIER_TEXT[b.tier] ?? b.tier}</dd>
            </div>
            <div>
              <dt className="text-sm text-fg-subtle">Grid cells · NASA requests</dt>
              <dd className="stat-num">
                {current.preflight.n_cells.toLocaleString()} · {current.preflight.n_tiles}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-fg-subtle">Observations</dt>
              <dd className="stat-num">{current.preflight.n_values.toLocaleString()} cell-months</dd>
            </div>
            {b.estimates && (
              <>
                <div>
                  <dt className="text-sm text-fg-subtle">Rough duration</dt>
                  <dd className="stat-num">
                    {minutes(b.estimates.total_seconds)} <span className="text-fg-subtle">(estimate)</span>
                  </dd>
                </div>
                <div>
                  <dt className="text-sm text-fg-subtle">Memory · storage</dt>
                  <dd className="stat-num">
                    ~{Math.round(b.estimates.memory_mb)} MB · ~{Math.round(b.estimates.storage_mb)} MB
                  </dd>
                </div>
              </>
            )}
          </dl>
          {b.estimates && <p className="text-xs text-fg-subtle">{b.estimates.note} Basis: {b.estimates.basis}.</p>}
          {b.eligible ? (
            <p className="flex items-center gap-2 text-sm text-teal">
              <CheckCircle2 className="size-4" aria-hidden /> Eligible for background processing.
            </p>
          ) : (
            <ul className="list-disc space-y-1 rounded-lg border border-warn/40 bg-warn/10 p-3 pl-8 text-sm" role="alert">
              {b.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
          <details className="text-sm">
            <summary className="cursor-pointer text-fg-muted">Processing stages</summary>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-fg-muted">
              {b.stages.map((s) => (
                <li key={s.id}>
                  <span className="text-fg">{s.label}</span> — {s.description}
                </li>
              ))}
            </ol>
          </details>
          <button type="button" className="btn-primary" onClick={start} disabled={!b.eligible || state !== 'idle'}>
            {state === 'submitting' && <Loader2 className="size-4 animate-spin" aria-hidden />}
            Start background analysis
          </button>
          <p className="text-xs text-fg-subtle">
            An accepted job is not a guaranteed result: it can still fail (for example if NASA POWER stays unavailable). It is never completed with
            missing tiles or synthetic substitutes.
          </p>
        </div>
      )}
    </section>
  )
}
