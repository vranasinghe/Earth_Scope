// All HTTP calls to the Earth Scope backend live here. Components never call
// fetch directly. The browser only talks to our backend; the backend talks to NASA.

import type {
  AnalysisParams,
  AnalysisResponse,
  ApiErrorBody,
  CompareParams,
  CompareResponse,
  DataResponse,
  GeocodeSearchResponse,
  RegionalAnalysisResponse,
  RegionalConfig,
  RegionalParams,
  ReverseGeocodeResponse,
  VariablesResponse,
} from '../types/api'
import type { SpatialCellDetail, SpatialCellParams, SpatialParams, SpatialTrendResponse } from '../types/spatial'
import type { AreaPreviewParams, AreaPreviewResponse, AreaRef, CountryListResponse } from '../types/area'
import type { Job, JobPreflightResponse, JobProgress, JobRequestParams, JobSubmitResponse, RetryResponse } from '../types/jobs'

// Same-origin "/api" by default: the Vite dev server and Vercel (frontend/vercel.json) proxy it to the
// backend, which keeps the job-session cookie first-party. Browsers drop cookies on cross-site calls
// (e.g. *.vercel.app -> *.onrender.com), so set VITE_API_ORIGIN only for a backend on the same site.
const BASE = (import.meta.env.VITE_API_ORIGIN as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: string[]
  readonly retryable: boolean
  readonly suggestedVariables: string[]

  constructor(status: number, body: Partial<ApiErrorBody>, fallback: string) {
    super(body.message || fallback)
    this.name = 'ApiError'
    this.status = status
    this.code = body.error || 'UNKNOWN_ERROR'
    this.details = body.details || []
    this.retryable = body.retryable ?? status >= 500
    this.suggestedVariables = body.suggested_variables || []
  }
}

export async function getJson<T>(
  path: string,
  params?: Record<string, string>,
  signal?: AbortSignal,
  payload?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const query = params ? `?${new URLSearchParams(params).toString()}` : ''
  let response: Response
  try {
    // credentials: the anonymous job-session cookie (HttpOnly) must accompany job requests.
    response = await fetch(
      `${BASE}${path}${query}`,
      payload === undefined
        ? { signal, credentials: 'include', headers: { Accept: 'application/json', ...extraHeaders } }
        : {
            signal,
            method: 'POST',
            credentials: 'include',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...extraHeaders },
            body: JSON.stringify(payload),
          },
    )
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(
      0,
      { error: 'BACKEND_UNREACHABLE', retryable: true },
      'Cannot reach the Earth Scope backend. Make sure it is running on port 8000 and try again.',
    )
  }

  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    const fallback =
      response.status === 502 || response.status === 504
        ? 'The Earth Scope backend is not responding. Make sure it is running and try again.'
        : `Request failed (HTTP ${response.status}).`
    throw new ApiError(response.status, (body as Partial<ApiErrorBody>) || {}, fallback)
  }
  if (body === null || typeof body !== 'object') {
    throw new ApiError(response.status, { error: 'INVALID_RESPONSE', retryable: true }, 'The backend returned an unexpected response.')
  }
  return body as T
}

function toQuery(p: AnalysisParams): Record<string, string> {
  return {
    variable: p.variable,
    latitude: String(p.latitude),
    longitude: String(p.longitude),
    start_year: String(p.startYear),
    end_year: String(p.endYear),
  }
}

function toCompareQuery(p: CompareParams): Record<string, string> {
  return {
    variable: p.variable,
    locations: p.locations.map((l) => `${l.latitude},${l.longitude}`).join(';'),
    labels: p.locations.map((l) => l.label.replace(/;/g, ',')).join(';'),
    start_year: String(p.startYear),
    end_year: String(p.endYear),
  }
}

function toRegionalQuery(p: RegionalParams): Record<string, string> {
  return {
    variable: p.variable,
    lat_min: String(p.bbox.lat_min),
    lat_max: String(p.bbox.lat_max),
    lon_min: String(p.bbox.lon_min),
    lon_max: String(p.bbox.lon_max),
    start_year: String(p.startYear),
    end_year: String(p.endYear),
    coverage_threshold: String(p.coverageThreshold),
  }
}

function toSpatialQuery(p: SpatialParams): Record<string, string> {
  return { ...toRegionalQuery(p), method: p.method, correction: p.correction, alpha: String(p.alpha) }
}

/** POST body for country / polygon analyses (the geometry travels in the body, not the URL). */
function areaBody(area: AreaRef, p: { variable: string; startYear: number; endYear: number }, extra: Record<string, unknown> = {}) {
  return {
    ...(area.kind === 'country' ? { iso3: area.iso3 } : { geometry: area.geometry, name: area.name }),
    variable: p.variable,
    start_year: p.startYear,
    end_year: p.endYear,
    ...extra,
  }
}

function regionalExtra(p: RegionalParams) {
  return { coverage_threshold: p.coverageThreshold }
}

function spatialExtra(p: SpatialParams) {
  return { ...regionalExtra(p), method: p.method, correction: p.correction, alpha: p.alpha }
}

// --- Background jobs -----------------------------------------------------------
// The session cookie identifies this browser's jobs; the CSRF token (returned by
// /api/analysis/session) must accompany every state-changing job request.

let sessionPromise: Promise<string> | null = null

/** Start or resume the anonymous analysis session; resolves to the CSRF token. */
export function ensureJobSession(): Promise<string> {
  if (!sessionPromise) {
    // Shared by every caller, so it is deliberately not tied to one component's AbortSignal.
    sessionPromise = getJson<{ csrf_token: string }>('/api/analysis/session')
      .then((r) => r.csrf_token)
      .catch((err: unknown) => {
        sessionPromise = null
        throw err
      })
  }
  return sessionPromise
}

/** Forget the cached session (tests; expired cookies). */
export function resetJobSession() {
  sessionPromise = null
}

async function jobPost<T>(path: string, payload: unknown, headers: Record<string, string> = {}): Promise<T> {
  const csrf = await ensureJobSession()
  try {
    return await getJson<T>(path, undefined, undefined, payload, { 'X-CSRF-Token': csrf, ...headers })
  } catch (err) {
    // The session may have expired (cookies cleared): start a new one once and retry.
    if (err instanceof ApiError && (err.code === 'CSRF_CHECK_FAILED' || err.code === 'SESSION_REQUIRED')) {
      resetJobSession()
      const fresh = await ensureJobSession()
      return getJson<T>(path, undefined, undefined, payload, { 'X-CSRF-Token': fresh, ...headers })
    }
    throw err
  }
}

async function jobGet<T>(path: string, params?: Record<string, string>, signal?: AbortSignal): Promise<T> {
  await ensureJobSession()
  return getJson<T>(path, params, signal)
}

function jobBody(p: JobRequestParams) {
  return areaBody(p.area, p, {
    coverage_threshold: p.coverageThreshold,
    method: p.method ?? 'mann_kendall',
    correction: p.correction ?? 'fdr_bh',
    alpha: p.alpha ?? 0.05,
  })
}

const jobPath = (id: string) => `/api/analysis/jobs/${encodeURIComponent(id)}`

export const jobsApi = {
  preflight: (p: JobRequestParams, signal?: AbortSignal) =>
    getJson<JobPreflightResponse>('/api/analysis/preflight', undefined, signal, jobBody(p)),
  submit: (p: JobRequestParams, idempotencyKey: string) =>
    jobPost<JobSubmitResponse>('/api/analysis/jobs', jobBody(p), { 'Idempotency-Key': idempotencyKey }),
  list: (signal?: AbortSignal) => jobGet<{ jobs: Job[] }>('/api/analysis/jobs', undefined, signal),
  get: (id: string, signal?: AbortSignal) => jobGet<Job>(jobPath(id), undefined, signal),
  progress: (id: string, signal?: AbortSignal) => jobGet<JobProgress>(`${jobPath(id)}/progress`, undefined, signal),
  cancel: (id: string) => jobPost<Job>(`${jobPath(id)}/cancel`, {}),
  retry: (id: string) => jobPost<RetryResponse>(`${jobPath(id)}/retry`, {}),
  artifactUrl: (id: string, name: string) => `${BASE}${jobPath(id)}/artifacts/${name}`,
}

export const api = {
  health: (signal?: AbortSignal) => getJson<{ status: string }>('/api/health', undefined, signal),
  variables: (signal?: AbortSignal) => getJson<VariablesResponse>('/api/variables', undefined, signal),
  data: (p: AnalysisParams, signal?: AbortSignal) => getJson<DataResponse>('/api/data', toQuery(p), signal),
  analyze: (p: AnalysisParams, signal?: AbortSignal) => getJson<AnalysisResponse>('/api/analyze', toQuery(p), signal),
  compare: (p: CompareParams, signal?: AbortSignal) => getJson<CompareResponse>('/api/compare', toCompareQuery(p), signal),
  /** Place search (server-side Nominatim). Call only on explicit submit — no autocomplete. */
  geocodeSearch: (q: string, signal?: AbortSignal) => getJson<GeocodeSearchResponse>('/api/geocode/search', { q }, signal),
  regionalConfig: (signal?: AbortSignal) => getJson<RegionalConfig>('/api/regional/config', undefined, signal),
  regionalAnalyze: (p: RegionalParams, signal?: AbortSignal) =>
    p.jobId
      ? jobGet<RegionalAnalysisResponse>(`${jobPath(p.jobId)}/results`, undefined, signal)
      : p.area
      ? getJson<RegionalAnalysisResponse>('/api/polygon/analyze', undefined, signal, areaBody(p.area, p, regionalExtra(p)))
      : getJson<RegionalAnalysisResponse>('/api/regional/analyze', toRegionalQuery(p), signal),
  spatialTrends: (p: SpatialParams, signal?: AbortSignal) =>
    p.jobId
      ? jobGet<SpatialTrendResponse>(`${jobPath(p.jobId)}/spatial`, { method: p.method, correction: p.correction, alpha: String(p.alpha) }, signal)
      : p.area
      ? getJson<SpatialTrendResponse>('/api/polygon/spatial-trends', undefined, signal, areaBody(p.area, p, spatialExtra(p)))
      : getJson<SpatialTrendResponse>('/api/regional/spatial-trends', toSpatialQuery(p), signal),
  spatialCell: (p: SpatialCellParams, signal?: AbortSignal) =>
    p.jobId
      ? jobGet<SpatialCellDetail>(
          `${jobPath(p.jobId)}/spatial/cell`,
          { cell_id: p.cellId, method: p.method, correction: p.correction, alpha: String(p.alpha) },
          signal,
        )
      : p.area
      ? getJson<SpatialCellDetail>('/api/polygon/spatial-trends/cell', undefined, signal, areaBody(p.area, p, { ...spatialExtra(p), cell_id: p.cellId }))
      : getJson<SpatialCellDetail>('/api/regional/spatial-trends/cell', { ...toSpatialQuery(p), cell_id: p.cellId }, signal),
  countries: (signal?: AbortSignal) => getJson<CountryListResponse>('/api/boundaries/countries', undefined, signal),
  areaPreview: (p: AreaPreviewParams, signal?: AbortSignal) =>
    p.area.kind === 'country'
      ? getJson<AreaPreviewResponse>(`/api/boundaries/countries/${encodeURIComponent(p.area.iso3)}`,
          { variable: p.variable, start_year: String(p.startYear), end_year: String(p.endYear) }, signal)
      : getJson<AreaPreviewResponse>('/api/polygon/preview', undefined, signal, areaBody(p.area, p)),
  geocodeReverse: (latitude: number, longitude: number, signal?: AbortSignal) =>
    getJson<ReverseGeocodeResponse>('/api/geocode/reverse', { latitude: String(latitude), longitude: String(longitude) }, signal),
}
