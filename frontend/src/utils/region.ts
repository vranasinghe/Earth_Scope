// Client-side region geometry. Mirrors backend/app/services/regional_grid.py so the
// preview (area, expected grid cells) updates instantly without a network request.
// The backend re-validates everything before contacting NASA.

import type { BBox, RegionalParams } from '../types/api'
import type { AreaRef } from '../types/area'
import { decodeGeometry, encodeGeometry, geometryBBox } from './polygon'

export const EARTH_RADIUS_KM = 6371.0088
const LAT_STEP = 0.5
const LON_STEP = 0.625
const rad = (d: number) => (d * Math.PI) / 180

/** Exact area of a latitude/longitude rectangle on a sphere (km²). */
export function sphericalAreaKm2(b: BBox): number {
  if (b.lat_max <= b.lat_min || b.lon_max <= b.lon_min) return 0
  return EARTH_RADIUS_KM ** 2 * rad(b.lon_max - b.lon_min) * (Math.sin(rad(b.lat_max)) - Math.sin(rad(b.lat_min)))
}

export interface CellPreview {
  lat: number
  lon: number
  bounds: [[number, number], [number, number]]
  partial: boolean
}

/** MERRA-2 cells overlapping the box (centres at k·0.5° lat, −180 + k·0.625° lon). */
export function expectedCells(b: BBox): CellPreview[] {
  const out: CellPreview[] = []
  const i0 = Math.ceil((b.lat_min - LAT_STEP / 2) / LAT_STEP - 1e-9)
  const i1 = Math.floor((b.lat_max + LAT_STEP / 2) / LAT_STEP + 1e-9)
  const j0 = Math.ceil((b.lon_min + 180 - LON_STEP / 2) / LON_STEP - 1e-9)
  const j1 = Math.floor((b.lon_max + 180 + LON_STEP / 2) / LON_STEP + 1e-9)
  for (let i = i0; i <= i1; i++) {
    const lat = i * LAT_STEP
    if (lat < -90 || lat > 90) continue
    for (let j = j0; j <= j1; j++) {
      const lon = -180 + j * LON_STEP
      if (lon >= 180) continue
      const la0 = Math.max(-90, lat - LAT_STEP / 2)
      const la1 = Math.min(90, lat + LAT_STEP / 2)
      const lo0 = lon - LON_STEP / 2
      const lo1 = lon + LON_STEP / 2
      const ov = sphericalAreaKm2({
        lat_min: Math.max(la0, b.lat_min),
        lat_max: Math.min(la1, b.lat_max),
        lon_min: Math.max(lo0, b.lon_min),
        lon_max: Math.min(lo1, b.lon_max),
      })
      if (ov <= 0) continue
      const full = sphericalAreaKm2({ lat_min: la0, lat_max: la1, lon_min: lo0, lon_max: lo1 })
      out.push({ lat, lon, bounds: [[la0, lo0], [la1, lo1]], partial: ov < full * 0.999 })
    }
  }
  return out
}

export interface BoxLimits {
  minSpan: number
  maxSpan: number
}

/** User-facing validation messages (empty array = valid). */
export function validateBox(b: BBox | null, limits: BoxLimits): string[] {
  if (!b) return ['Draw a rectangle on the map, choose a preset, or enter the four coordinates.']
  const errs: string[] = []
  const vals = [b.lat_min, b.lat_max, b.lon_min, b.lon_max]
  if (vals.some((v) => !Number.isFinite(v))) return ['All four bounding-box values must be numbers.']
  if (b.lat_min < -90 || b.lat_max > 90) errs.push('Latitude must be between −90 and 90.')
  if (b.lon_min < -180 || b.lon_max > 180) errs.push('Longitude must be between −180 and 180.')
  if (b.lat_min >= b.lat_max) errs.push('Minimum latitude must be smaller than maximum latitude.')
  if (b.lon_min >= b.lon_max)
    errs.push('Minimum longitude must be smaller than maximum longitude (regions crossing ±180° are not supported).')
  if (errs.length) return errs
  const h = b.lat_max - b.lat_min
  const w = b.lon_max - b.lon_min
  if (h < limits.minSpan || w < limits.minSpan)
    errs.push(`Each side must span at least ${limits.minSpan}° (currently ${h.toFixed(2)}° × ${w.toFixed(2)}°). Use Point Analysis for smaller areas.`)
  if (h > limits.maxSpan || w > limits.maxSpan)
    errs.push(`Region too large: each side may span at most ${limits.maxSpan}° (currently ${h.toFixed(2)}° × ${w.toFixed(2)}°).`)
  return errs
}

export function complexityLabel(cells: number): { label: string; tone: 'ok' | 'warn' } {
  if (cells <= 60) return { label: 'Light — one small NASA request', tone: 'ok' }
  if (cells <= 180) return { label: 'Moderate — one NASA request', tone: 'ok' }
  return { label: 'Heavy — one large NASA request (may take several seconds)', tone: 'warn' }
}

export function roundBox(b: BBox, digits = 2): BBox {
  const r = (v: number) => Number(v.toFixed(digits))
  return { lat_min: r(b.lat_min), lat_max: r(b.lat_max), lon_min: r(b.lon_min), lon_max: r(b.lon_max) }
}

// --- URL helpers -----------------------------------------------------------------

const POLY_URL_LIMIT = 6000

/** Store a large polygon in sessionStorage and return its key (URLs stay short). */
function stashPolygon(encoded: string): string {
  let h = 0
  for (let i = 0; i < encoded.length; i++) h = (Math.imul(31, h) + encoded.charCodeAt(i)) | 0
  const key = `es-poly-${(h >>> 0).toString(36)}`
  try {
    sessionStorage.setItem(key, encoded)
  } catch {
    /* storage unavailable: the long URL form is used instead */
    return ''
  }
  return key
}

const JOB_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

/** Results URL of a completed background job: the job id is the only parameter (its stored config defines everything). */
export function jobResultsPath(jobId: string): string {
  return `/regional/results?job=${encodeURIComponent(jobId)}`
}

export function isJobId(v: string | null | undefined): v is string {
  return !!v && JOB_ID_RE.test(v)
}

export function toRegionalSearch(p: RegionalParams): string {
  if (p.jobId) return `?job=${encodeURIComponent(p.jobId)}`
  const b = p.area ? roundBox(p.bbox, 4) : p.bbox // display only for areas; the geometry defines the analysis
  const q = new URLSearchParams({
    variable: p.variable,
    lat_min: String(b.lat_min),
    lat_max: String(b.lat_max),
    lon_min: String(b.lon_min),
    lon_max: String(b.lon_max),
    start: String(p.startYear),
    end: String(p.endYear),
    coverage: String(p.coverageThreshold),
  })
  if (p.area?.kind === 'country') {
    q.set('shape', 'country')
    q.set('iso3', p.area.iso3)
  } else if (p.area?.kind === 'polygon') {
    q.set('shape', 'polygon')
    q.set('name', p.area.name)
    const enc = encodeGeometry(p.area.geometry)
    const key = enc.length > POLY_URL_LIMIT ? stashPolygon(enc) : ''
    if (key) q.set('polyref', key)
    else q.set('poly', enc)
  }
  return `?${q.toString()}`
}

/** 'rectangle' | 'country' | 'polygon' from the URL. */
export function shapeOf(s: URLSearchParams): 'rectangle' | 'country' | 'polygon' {
  const v = s.get('shape')
  return v === 'country' || v === 'polygon' ? v : 'rectangle'
}

function areaFromSearch(s: URLSearchParams): AreaRef | null | undefined {
  const shape = shapeOf(s)
  if (shape === 'country') {
    const iso3 = (s.get('iso3') ?? '').toUpperCase()
    return /^[A-Z]{3}$/.test(iso3) ? { kind: 'country', iso3 } : null
  }
  if (shape === 'polygon') {
    let enc = s.get('poly')
    const ref = s.get('polyref')
    if (!enc && ref) {
      try {
        enc = sessionStorage.getItem(ref)
      } catch {
        enc = null
      }
    }
    const geometry = enc ? decodeGeometry(enc) : null
    return geometry ? { kind: 'polygon', geometry, name: s.get('name') || 'Custom polygon' } : null
  }
  return undefined
}

export function fromRegionalSearch(s: URLSearchParams): RegionalParams | null {
  const job = s.get('job')
  if (job !== null) {
    if (!isJobId(job)) return null
    // Placeholders only: the stored job result carries its own variable, period, area and data mode.
    return { variable: '', bbox: { lat_min: 0, lat_max: 0, lon_min: 0, lon_max: 0 }, startYear: 0, endYear: 0, coverageThreshold: 0.8, jobId: job }
  }
  const need = ['variable', 'start', 'end']
  if (!need.every((k) => s.get(k) !== null && s.get(k) !== '')) return null
  const n = (k: string) => Number(s.get(k))
  const area = areaFromSearch(s)
  if (area === null) return null // a country / polygon was requested but cannot be restored: never fall back to a rectangle
  let bbox: BBox
  if (area?.kind === 'polygon') bbox = geometryBBox(area.geometry)
  else if (['lat_min', 'lat_max', 'lon_min', 'lon_max'].every((k) => s.get(k) !== null && s.get(k) !== ''))
    bbox = { lat_min: n('lat_min'), lat_max: n('lat_max'), lon_min: n('lon_min'), lon_max: n('lon_max') }
  else if (area?.kind === 'country') bbox = { lat_min: 0, lat_max: 0, lon_min: 0, lon_max: 0 } // filled from the response
  else return null
  if (![...Object.values(bbox), n('start'), n('end')].every(Number.isFinite)) return null
  const cov = s.get('coverage') !== null ? n('coverage') : 0.8
  return {
    variable: s.get('variable')!, bbox, startYear: n('start'), endYear: n('end'),
    coverageThreshold: Number.isFinite(cov) ? cov : 0.8, ...(area ? { area } : {}),
  }
}
