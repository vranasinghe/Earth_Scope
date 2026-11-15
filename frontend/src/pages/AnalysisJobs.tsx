import { ArrowRight, Layers } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { SectionHeading } from '../components/common/SectionHeading'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { JobCard } from '../components/jobs/JobParts'
import { confirmCancel } from '../utils/jobs'
import { useJobList, useJobSession } from '../hooks/useJobs'
import { ApiError, jobsApi } from '../services/api'
import type { Job } from '../types/jobs'
import { ACTIVE_STATUSES } from '../types/jobs'

const GROUPS: { id: string; title: string; match: (j: Job) => boolean; empty: string }[] = [
  { id: 'current', title: 'Current', match: (j) => ACTIVE_STATUSES.has(j.status), empty: 'No analysis is queued or running.' },
  { id: 'completed', title: 'Completed', match: (j) => j.status === 'COMPLETED', empty: 'No completed analyses yet.' },
  { id: 'failed', title: 'Failed', match: (j) => j.status === 'FAILED', empty: 'No failed analyses.' },
  { id: 'cancelled', title: 'Cancelled & expired', match: (j) => j.status === 'CANCELLED' || j.status === 'EXPIRED', empty: 'Nothing here.' },
]

/** Background analyses of THIS browser session only (the server never lists other sessions' jobs). */
export default function AnalysisJobs() {
  const sessionError = useJobSession()
  const { data, error, loading, refresh } = useJobList()
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<ApiError | null>(null)
  const navigate = useNavigate()

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setActionError(null)
    try {
      await fn()
    } catch (err) {
      setActionError(err instanceof ApiError ? err : new ApiError(0, {}, 'The action failed.'))
    } finally {
      setBusy(false)
      refresh()
    }
  }
  const onCancel = (j: Job) => {
    if (confirmCancel(j)) void act(() => jobsApi.cancel(j.job_id))
  }
  const onRetry = (j: Job) => void act(async () => navigate(`/jobs/${(await jobsApi.retry(j.job_id)).job.job_id}`))

  const jobs = data?.jobs ?? []
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 sm:px-6">
      <header className="mb-10">
        <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">Analysis jobs</h1>
        <p className="measure mt-2 text-fg-muted">
          Large country and polygon analyses run on Earth Scope&apos;s servers. Close the tab if you like; this browser can come back for the
          progress and the results.
        </p>
      </header>

      {sessionError && <ErrorState error={sessionError} title="Could not start an analysis session" />}
      {actionError && (
        <div className="mb-6">
          <ErrorState error={actionError} title="The action could not be completed" />
        </div>
      )}
      {error && !data && <ErrorState error={error} title="Could not load your analysis jobs" onRetry={refresh} />}
      {loading && !data && <LoadingState title="Loading your analysis jobs…" />}

      {data && jobs.length === 0 && (
        <div className="grid gap-10 border-t border-line pt-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-16">
          <div>
            <Layers className="size-7 text-accent" aria-hidden />
            <h2 className="mt-4 text-xl font-bold">No background analyses yet</h2>
            <p className="measure mt-2 text-fg-muted">
              When a country or polygon is too large for an instant answer, start it as a background analysis from the regional page. It
              will appear here with live progress.
            </p>
            <Link to="/regional?shape=country" className="btn-primary mt-6">
              Choose a country or polygon <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
          <dl className="divide-y divide-line border-y border-line">
            {[
              ['Runs without your browser', 'NASA tiles are downloaded and analysed by a server worker; nothing depends on this tab staying open.'],
              ['Survives interruptions', 'Verified tiles and finished statistics are saved as checkpoints, so a restart resumes instead of starting over.'],
              ['Same science, same result', 'A background result is identical to the instant one and opens in the same results pages, with exports.'],
              ['Private to this browser', 'Jobs are tied to this browser session and kept for 14 days after they finish.'],
            ].map(([t, d]) => (
              <div key={t} className="py-4">
                <dt className="font-semibold">{t}</dt>
                <dd className="mt-1 text-[0.9375rem] text-fg-muted">{d}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {data && jobs.length > 0 && (
        <div className="space-y-10">
          {error && <Notice tone="warn">Connection problem — showing the last known state; retrying automatically.</Notice>}
          {GROUPS.map((g) => {
            const list = jobs.filter(g.match)
            if (!list.length && g.id !== 'current') return null
            return (
              <section key={g.id} aria-labelledby={`group-${g.id}`}>
                <SectionHeading id={`group-${g.id}`} title={`${g.title} (${list.length})`} />
                {list.length ? (
                  <div className="grid gap-4 md:grid-cols-2">
                    {list.map((j) => (
                      <JobCard key={j.job_id} job={j} onCancel={onCancel} onRetry={onRetry} busy={busy} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-fg-muted">{g.empty}</p>
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
