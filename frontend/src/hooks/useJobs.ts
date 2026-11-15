import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, ensureJobSession, jobsApi } from '../services/api'
import { ACTIVE_STATUSES } from '../types/jobs'
import type { Job } from '../types/jobs'

/**
 * Polling interval for an active job: every 2 s for the first minute it is watched,
 * then every 5 s; a hidden browser tab polls at most every 15 s. Errors back off
 * exponentially up to 30 s. Nothing here simulates progress: every number shown
 * comes from the backend's work counters.
 */
export function pollDelay(watchedMs: number, hidden: boolean, failures: number): number {
  if (failures > 0) return Math.min(30_000, 2_000 * 2 ** failures)
  const base = watchedMs < 60_000 ? 2_000 : 5_000
  return hidden ? Math.max(base, 15_000) : base
}

const isHidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden'

interface PollState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
}

/** One polling loop per mounted hook; stops when `isActive(data)` is false, restarts on refresh(). */
function usePolling<T>(key: string | null, fetcher: (signal: AbortSignal) => Promise<T>, isActive: (d: T) => boolean) {
  const [state, setState] = useState<Omit<PollState<T>, 'loading'>>({ data: null, error: null })
  const [nonce, setNonce] = useState(0)
  const fetcherRef = useRef(fetcher)
  const activeRef = useRef(isActive)
  useEffect(() => {
    fetcherRef.current = fetcher
    activeRef.current = isActive
  })

  useEffect(() => {
    if (key === null) return
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    const started = Date.now()
    const controller = new AbortController()

    const tick = async () => {
      try {
        const data = await fetcherRef.current(controller.signal)
        if (stopped) return
        failures = 0
        setState({ data, error: null })
        if (!activeRef.current(data)) return // finished: no more polling
      } catch (err) {
        if (stopped || (err as Error).name === 'AbortError') return
        failures += 1
        const error = err instanceof ApiError ? err : new ApiError(0, {}, 'Could not load the job status.')
        setState((s) => ({ ...s, error }))
        if (error.status === 404 || error.status === 401) return // not this session's job: polling cannot help
      }
      timer = setTimeout(tick, pollDelay(Date.now() - started, isHidden(), failures))
    }
    void tick()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      controller.abort()
    }
  }, [key, nonce])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, loading: key !== null && state.data === null && state.error === null, refresh }
}

/** One job, polled while it is queued or running (survives page refresh: state always comes from the backend). */
export function useJob(jobId: string | null) {
  return usePolling<Job>(
    jobId,
    (signal) => jobsApi.get(jobId as string, signal),
    (j) => ACTIVE_STATUSES.has(j.status),
  )
}

/** This browser session's jobs, polled while any of them is active. */
export function useJobList() {
  return usePolling<{ jobs: Job[] }>(
    'list',
    (signal) => jobsApi.list(signal),
    (d) => d.jobs.some((j) => ACTIVE_STATUSES.has(j.status)),
  )
}

/** Start the anonymous session early so the first job action is not delayed. */
export function useJobSession() {
  const [error, setError] = useState<ApiError | null>(null)
  useEffect(() => {
    let live = true
    ensureJobSession().catch((err: unknown) => {
      if (live) setError(err instanceof ApiError ? err : new ApiError(0, {}, 'Could not start a session.'))
    })
    return () => {
      live = false
    }
  }, [])
  return error
}
