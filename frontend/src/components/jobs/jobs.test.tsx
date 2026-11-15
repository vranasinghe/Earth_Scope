import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { pollDelay } from '../../hooks/useJobs'
import JobDetails from '../../pages/JobDetails'
import AnalysisJobs from '../../pages/AnalysisJobs'
import { api, resetJobSession } from '../../services/api'
import type { Job, JobStatus } from '../../types/jobs'
import { fromRegionalSearch, toRegionalSearch } from '../../utils/region'
import { BackgroundJobPanel } from './BackgroundJobPanel'
import { JobCard } from './JobParts'

const ID = '3f2b8c1e-9a4d-4c2b-8e1f-0a1b2c3d4e5f'

function job(status: JobStatus, over: Partial<Job> = {}): Job {
  const pct = status === 'COMPLETED' ? 100 : status === 'RUNNING' ? 37 : 0
  return {
    job_id: ID, job_type: 'area_analysis', status, tier: 'MEDIUM', data_mode: 'LIVE',
    area: { kind: 'country', name: 'United States', iso3: 'USA', geometry_id: 'g1', boundary_source: 'geoBoundaries', boundary_version: 'gbOpen commit 9469f09' },
    variable_id: 'air_temperature', parameter: 'T2M', community: 'AG', start_year: 2001, end_year: 2025, config: {}, config_hash: 'abcdef0123456789abcdef',
    preflight: { n_cells: 4089, n_tiles: 44 },
    progress: {
      job_id: ID, status, stage: status === 'COMPLETED' ? 'COMPLETED' : 'DOWNLOADING_NASA_DATA', stage_label: status === 'COMPLETED' ? 'Completed' : 'Downloading NASA data',
      activity: 'Downloading 44 NASA POWER tiles', progress_pct: pct, is_active: ['QUEUED', 'RUNNING', 'PENDING', 'RETRYING', 'CANCEL_REQUESTED'].includes(status),
      download: { tiles_completed: status === 'COMPLETED' ? 44 : 17, tiles_total: 44, tiles_retrying: 1, tiles_failed: 0 },
      processing: { cells_processed: 0, cells_total: 4089 }, attempts: { total: 1, automatic: 1, max_automatic: 3, manual_retries: 0 },
      updated_at: '2026-11-15T10:00:00+00:00', heartbeat_at: null,
      stages: [{ id: 'PREPARING_GEOMETRY', label: 'Preparing geometry', state: 'done' }, { id: 'DOWNLOADING_NASA_DATA', label: 'Downloading NASA data', state: 'current' }],
    },
    error: status === 'FAILED' ? { code: 'INCOMPLETE_TILE_RETRIEVAL', message: '1 of 44 NASA POWER requests failed', retryable: true } : null,
    created_at: '2026-11-15T09:58:00+00:00', queued_at: null, started_at: null, updated_at: null, completed_at: null, expires_at: null,
    software_version: 'earthscope-analysis-6.0.0', dataset_version: 'NASA POWER Monthly Regional API', can_cancel: ['QUEUED', 'RUNNING'].includes(status),
    can_retry: status === 'FAILED', has_results: status === 'COMPLETED', links: {}, events: [],
    ...over,
  }
}

type Handler = (url: string, init?: RequestInit) => unknown
let calls: { url: string; init?: RequestInit }[] = []

function mockFetch(handler: Handler) {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    if (url.includes('/api/analysis/session')) return new Response(JSON.stringify({ active: true, csrf_token: 'csrf-123' }), { status: 200 })
    const body = handler(url, init)
    if (body instanceof Response) return body
    return new Response(JSON.stringify(body), { status: 200 })
  }))
}

beforeEach(() => resetJobSession())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('polling cadence', () => {
  it('polls quickly at first, slower later, rarely when hidden, and backs off on errors', () => {
    expect(pollDelay(1_000, false, 0)).toBe(2_000)
    expect(pollDelay(120_000, false, 0)).toBe(5_000)
    expect(pollDelay(1_000, true, 0)).toBe(15_000)
    expect(pollDelay(1_000, false, 3)).toBe(16_000)
    expect(pollDelay(1_000, false, 10)).toBe(30_000)
  })
})

describe('JobCard', () => {
  const card = (j: Job, props = {}) => render(<MemoryRouter><JobCard job={j} {...props} /></MemoryRouter>)

  it('shows real progress counters and a cancel action for a running job', () => {
    const onCancel = vi.fn()
    card(job('RUNNING'), { onCancel })
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '37')
    expect(screen.getByText('17 / 44')).toBeInTheDocument()
    expect(screen.getByText(/1 retrying/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
    expect(screen.queryByRole('link', { name: 'View results' })).toBeNull()
  })
  it('links completed jobs to the existing results dashboard', () => {
    card(job('COMPLETED'))
    expect(screen.getByRole('link', { name: 'View results' })).toHaveAttribute('href', `/regional/results?job=${ID}`)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  })
  it('offers retry for retryable failures', () => {
    const onRetry = vi.fn()
    card(job('FAILED'), { onRetry })
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(onRetry).toHaveBeenCalled()
    expect(screen.getByText(/INCOMPLETE_TILE_RETRIEVAL/)).toBeInTheDocument()
  })
})

describe('Job details page', () => {
  const page = () =>
    render(
      <MemoryRouter initialEntries={[`/jobs/${ID}`]}>
        <Routes>
          <Route path="/jobs/:jobId" element={<JobDetails />} />
        </Routes>
      </MemoryRouter>,
    )

  it('loads the current state from the backend (a refresh never resets progress) and stops polling when done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let n = 0
    mockFetch((url) => (url.endsWith(ID) ? job(++n < 2 ? 'RUNNING' : 'COMPLETED') : {}))
    page()
    await waitFor(() => expect(screen.getByRole('progressbar', { name: 'Overall analysis progress' })).toHaveAttribute('aria-valuenow', '37'))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100)
    })
    await waitFor(() => expect(screen.getByRole('link', { name: 'View results' })).toBeInTheDocument())
    const polls = calls.filter((c) => c.url.endsWith(ID)).length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })
    expect(calls.filter((c) => c.url.endsWith(ID)).length).toBe(polls) // no polling after completion
    expect(screen.getAllByRole('link', { name: /CSV/ })[0]).toHaveAttribute('href', expect.stringContaining('/artifacts/exports/'))
  })

  it('cancels with the CSRF header after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockFetch((_url, init) => (init?.method === 'POST' ? job('CANCEL_REQUESTED') : job('RUNNING')))
    page()
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel analysis' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/cancel'))).toBe(true))
    const post = calls.find((c) => c.url.endsWith('/cancel'))!
    expect((post.init!.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-123')
    expect(post.init!.credentials).toBe('include')
  })

  it('explains that jobs are private when the backend answers 404', async () => {
    mockFetch(() => new Response(JSON.stringify({ error: 'JOB_NOT_FOUND', message: 'No analysis job with this id exists for your session.' }), { status: 404 }))
    page()
    expect(await screen.findByText(/does not exist for this browser session/)).toBeInTheDocument()
  })

  it('reports a retry with the number of reusable tiles', async () => {
    mockFetch((_url, init) =>
      init?.method === 'POST'
        ? { job: job('QUEUED'), resumable: { verified_tiles: 43, tiles_total: 44, checkpoints: [], statistics_chunks_done: 0 } }
        : job('FAILED'),
    )
    page()
    fireEvent.click(await screen.findByRole('button', { name: /Retry analysis/ }))
    expect(await screen.findByText(/43 of 44 NASA tiles are already verified/)).toBeInTheDocument()
  })
})

describe('Analysis Jobs dashboard', () => {
  it('groups only this session’s jobs by state', async () => {
    mockFetch(() => ({ jobs: [job('RUNNING'), job('COMPLETED', { job_id: 'b' + ID.slice(1) }), job('FAILED', { job_id: 'c' + ID.slice(1) })] }))
    render(<MemoryRouter><AnalysisJobs /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: 'Current (1)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Completed (1)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Failed (1)' })).toBeInTheDocument()
  })
  it('shows an empty state with a way to start', async () => {
    mockFetch(() => ({ jobs: [] }))
    render(<MemoryRouter><AnalysisJobs /></MemoryRouter>)
    expect(await screen.findByRole('link', { name: /Choose a country/ })).toHaveAttribute('href', '/regional?shape=country')
  })
})

const PREFLIGHT = {
  area: {}, variable: 'air_temperature', start_year: 2001, end_year: 2025, data_mode: 'LIVE',
  preflight: { n_cells: 4089, n_tiles: 44, n_values: 1226700, n_months: 300 },
  background: { tier: 'MEDIUM', eligible: true, synchronous_available: false, reasons: [], config_hash: 'x', limits: {},
    estimates: { basis: 'static benchmark', download_seconds: 45, processing_seconds: 30, total_seconds: 75, memory_mb: 400, storage_mb: 80, note: 'Estimates, not guarantees.' },
    stages: [{ id: 'DOWNLOADING_NASA_DATA', label: 'Downloading NASA data', description: 'Fetch every tile' }] },
}

describe('BackgroundJobPanel', () => {
  const params = { area: { kind: 'country' as const, iso3: 'USA' }, variable: 'air_temperature', startYear: 2001, endYear: 2025, coverageThreshold: 0.8 }
  const panel = () =>
    render(
      <MemoryRouter initialEntries={['/regional']}>
        <Routes>
          <Route path="/regional" element={<BackgroundJobPanel params={params} disabledReason={null} />} />
          <Route path="/jobs/:jobId" element={<p>job page</p>} />
        </Routes>
      </MemoryRouter>,
    )

  it('previews requirements, then submits once with an idempotency key and opens the job page', async () => {
    let resolveSubmit: (r: Response) => void = () => {}
    mockFetch((url) => {
      if (url.endsWith('/preflight')) return PREFLIGHT
      return new Promise<Response>((r) => (resolveSubmit = r))
    })
    panel()
    fireEvent.click(screen.getByRole('button', { name: /Preview analysis requirements/ }))
    expect(await screen.findByText(/Medium — runs on a background worker/)).toBeInTheDocument()
    expect(screen.getByText(/4,089 · 44/)).toBeInTheDocument()
    expect(screen.getByText(/Estimates, not guarantees/)).toBeInTheDocument()
    const start = screen.getByRole('button', { name: /Start background analysis/ })
    fireEvent.click(start)
    fireEvent.click(start) // double click
    await waitFor(() => expect(calls.filter((c) => c.url.endsWith('/api/analysis/jobs')).length).toBe(1))
    const post = calls.find((c) => c.url.endsWith('/api/analysis/jobs'))!
    const headers = post.init!.headers as Record<string, string>
    expect(headers['Idempotency-Key']).toBeTruthy()
    expect(headers['X-CSRF-Token']).toBe('csrf-123')
    expect(JSON.parse(post.init!.body as string)).toMatchObject({ iso3: 'USA', method: 'mann_kendall', correction: 'fdr_bh' })
    resolveSubmit(new Response(JSON.stringify({ job_id: ID, status: 'QUEUED', created: true }), { status: 202 }))
    expect(await screen.findByText('job page')).toBeInTheDocument()
  })

  it('shows the reasons when an area exceeds the background budget', async () => {
    mockFetch(() => ({ ...PREFLIGHT, background: { ...PREFLIGHT.background, tier: 'VERY_LARGE', eligible: false, reasons: ['It exceeds the LARGE background tier.'] } }))
    panel()
    fireEvent.click(screen.getByRole('button', { name: /Preview analysis requirements/ }))
    expect(await screen.findByText('It exceeds the LARGE background tier.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Start background analysis/ })).toBeDisabled()
  })
})

describe('completed jobs load through the existing result pathway', () => {
  it('routes results, spatial maps and cell details to the job endpoints', async () => {
    mockFetch(() => ({}))
    const p = fromRegionalSearch(new URLSearchParams(`job=${ID}`))!
    expect(p.jobId).toBe(ID)
    expect(toRegionalSearch(p)).toBe(`?job=${ID}`)
    await api.regionalAnalyze(p)
    await api.spatialTrends({ ...p, method: 'mann_kendall', correction: 'fdr_by', alpha: 0.1 })
    await api.spatialCell({ ...p, method: 'mann_kendall', correction: 'fdr_bh', alpha: 0.05, cellId: '7.000_80.6250' })
    const urls = calls.map((c) => c.url).filter((u) => !u.includes('/session'))
    expect(urls[0]).toBe(`/api/analysis/jobs/${ID}/results`)
    expect(urls[1]).toBe(`/api/analysis/jobs/${ID}/spatial?method=mann_kendall&correction=fdr_by&alpha=0.1`)
    expect(urls[2]).toContain(`/api/analysis/jobs/${ID}/spatial/cell?cell_id=7.000_80.6250`)
  })
  it('rejects malformed job links', () => {
    expect(fromRegionalSearch(new URLSearchParams('job=../../etc'))).toBeNull()
  })
})
