// Client-side polygon helpers. They give instant feedback while drawing; the backend
// re-validates every geometry (validity, area, limits) before anything is analysed.

import type { BBox } from '../types/api'
import type { AreaGeometry, Position } from '../types/area'

export type LatLng = [number, number] // [lat, lng] (Leaflet order)

export const MAX_VERTICES = 5000
export const MAX_UPLOAD_BYTES = 2_000_000

/** Leaflet vertices → closed GeoJSON Polygon ([lon, lat]). */
export function verticesToGeometry(v: LatLng[]): AreaGeometry {
  const ring: Position[] = v.map(([lat, lng]) => [round(lng), round(lat)])
  ring.push([...ring[0]] as Position)
  return { type: 'Polygon', coordinates: [ring] }
}

const round = (x: number) => Math.round(x * 1e6) / 1e6

function distinct(v: LatLng[]): number {
  return new Set(v.map(([a, b]) => `${a.toFixed(9)},${b.toFixed(9)}`)).size
}

function orient(a: LatLng, b: LatLng, c: LatLng): number {
  return (b[1] - a[1]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[1] - a[1])
}

function onSegment(a: LatLng, b: LatLng, p: LatLng): boolean {
  return Math.min(a[0], b[0]) <= p[0] && p[0] <= Math.max(a[0], b[0]) && Math.min(a[1], b[1]) <= p[1] && p[1] <= Math.max(a[1], b[1])
}

function segmentsIntersect(p1: LatLng, p2: LatLng, p3: LatLng, p4: LatLng): boolean {
  const d1 = orient(p3, p4, p1)
  const d2 = orient(p3, p4, p2)
  const d3 = orient(p1, p2, p3)
  const d4 = orient(p1, p2, p4)
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) return true
  if (d1 === 0 && onSegment(p3, p4, p1)) return true
  if (d2 === 0 && onSegment(p3, p4, p2)) return true
  if (d3 === 0 && onSegment(p1, p2, p3)) return true
  if (d4 === 0 && onSegment(p1, p2, p4)) return true
  return false
}

/** True if any two non-adjacent edges of the closed ring cross or touch. */
export function selfIntersects(v: LatLng[]): boolean {
  const n = v.length
  if (n < 4) return false
  for (let i = 0; i < n; i++) {
    const a = v[i]
    const b = v[(i + 1) % n]
    for (let j = i + 1; j < n; j++) {
      if (Math.abs(i - j) <= 1 || (i === 0 && j === n - 1)) continue
      if (segmentsIntersect(a, b, v[j], v[(j + 1) % n])) return true
    }
  }
  return false
}

/** True if every vertex lies on one straight line (zero area). A symmetric bow-tie has zero
 *  signed area but is not collinear, so this — not the signed area — is the right test. */
function allCollinear(v: LatLng[]): boolean {
  const a = v[0]
  const b = v.find((p) => Math.abs(p[0] - a[0]) > 1e-12 || Math.abs(p[1] - a[1]) > 1e-12)
  if (!b) return true
  return v.every((p) => Math.abs(orient(a, b, p)) < 1e-12)
}

/** Messages shown while drawing (empty = locally valid). */
export function validateVertices(v: LatLng[], maxVertices = MAX_VERTICES): string[] {
  if (v.length === 0) return []
  const errs: string[] = []
  if (distinct(v) < 3) errs.push('A polygon needs at least three distinct vertices.')
  if (v.some(([a, b]) => !Number.isFinite(a) || !Number.isFinite(b))) errs.push('All coordinates must be finite numbers.')
  if (v.some(([a]) => a < -90 || a > 90)) errs.push('Latitude must be between −90 and 90.')
  if (v.length > maxVertices) errs.push(`At most ${maxVertices} vertices are allowed.`)
  if (errs.length) return errs
  if (allCollinear(v)) errs.push('The polygon has zero area (its vertices lie on one line).')
  else if (selfIntersects(v)) errs.push('Edges cross each other. Move or delete a vertex so the outline does not intersect itself.')
  return errs
}

export function countVertices(g: AreaGeometry): number {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  return polys.reduce((s, p) => s + p.reduce((t, r) => t + Math.max(0, r.length - 1), 0), 0)
}

export function geometryBBox(g: AreaGeometry): BBox {
  let lat_min = Infinity
  let lat_max = -Infinity
  let lon_min = Infinity
  let lon_max = -Infinity
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  for (const p of polys)
    for (const r of p)
      for (const [lon, lat] of r) {
        lat_min = Math.min(lat_min, lat)
        lat_max = Math.max(lat_max, lat)
        lon_min = Math.min(lon_min, lon)
        lon_max = Math.max(lon_max, lon)
      }
  return { lat_min, lat_max, lon_min, lon_max }
}

/** Editable vertices for a single polygon without holes; null otherwise (shown read-only). */
export function editableVertices(g: AreaGeometry): LatLng[] | null {
  if (g.type !== 'Polygon' || g.coordinates.length !== 1) return null
  const ring = g.coordinates[0].slice(0, -1)
  return ring.map(([lon, lat]) => [lat, lon])
}

// --- GeoJSON upload ------------------------------------------------------------

function asPolygons(obj: unknown): Position[][][] {
  if (!obj || typeof obj !== 'object') throw new Error('The file is not a GeoJSON object.')
  const o = obj as { type?: unknown; geometry?: unknown; features?: unknown; coordinates?: unknown }
  switch (o.type) {
    case 'Feature':
      return asPolygons(o.geometry)
    case 'FeatureCollection': {
      if (!Array.isArray(o.features) || o.features.length === 0) throw new Error('The FeatureCollection has no features.')
      return o.features.flatMap((f) => asPolygons((f as { geometry?: unknown })?.geometry))
    }
    case 'Polygon':
      return [checkPolygon(o.coordinates)]
    case 'MultiPolygon':
      if (!Array.isArray(o.coordinates)) throw new Error('MultiPolygon coordinates must be an array.')
      return o.coordinates.map(checkPolygon)
    default:
      throw new Error(`Unsupported geometry type "${String(o.type)}". Only Polygon and MultiPolygon areas can be analysed.`)
  }
}

function checkPolygon(rings: unknown): Position[][] {
  if (!Array.isArray(rings) || rings.length === 0) throw new Error('A polygon has no rings.')
  return rings.map((r) => {
    if (!Array.isArray(r) || r.length < 4) throw new Error('Each ring needs at least four positions (closed).')
    return r.map((p) => {
      if (!Array.isArray(p) || p.length < 2 || !p.slice(0, 2).every((x) => typeof x === 'number' && Number.isFinite(x)))
        throw new Error('Every position must be [longitude, latitude] with finite numbers.')
      return [p[0], p[1]] as Position
    })
  })
}

/** Parse an uploaded GeoJSON file strictly. Never follows URLs or executes anything. */
export function parseGeoJSONText(text: string, maxVertices = MAX_VERTICES): AreaGeometry {
  if (text.length > MAX_UPLOAD_BYTES) throw new Error(`The file is larger than ${MAX_UPLOAD_BYTES / 1_000_000} MB.`)
  let obj: unknown
  try {
    obj = JSON.parse(text)
  } catch {
    throw new Error('The file is not valid JSON.')
  }
  const polys = asPolygons(obj)
  const g: AreaGeometry = polys.length === 1 ? { type: 'Polygon', coordinates: polys[0] } : { type: 'MultiPolygon', coordinates: polys }
  if (countVertices(g) > maxVertices) throw new Error(`The geometry has more than ${maxVertices} vertices; simplify it first.`)
  return g
}

// --- URL encoding --------------------------------------------------------------

/** Compact text form: parts '~', rings '!', vertices ';', 'lon,lat' with 5 decimals. */
export function encodeGeometry(g: AreaGeometry): string {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  return polys
    .map((p) => p.map((r) => r.slice(0, -1).map(([lon, lat]) => `${+lon.toFixed(5)},${+lat.toFixed(5)}`).join(';')).join('!'))
    .join('~')
}

export function decodeGeometry(s: string): AreaGeometry | null {
  try {
    const polys = s.split('~').map((p) =>
      p.split('!').map((r) => {
        const ring = r.split(';').map((v) => v.split(',').map(Number) as Position)
        if (ring.length < 3 || ring.some((x) => x.length !== 2 || !x.every(Number.isFinite))) throw new Error('bad')
        return [...ring, [...ring[0]] as Position]
      }),
    )
    return polys.length === 1 ? { type: 'Polygon', coordinates: polys[0] } : { type: 'MultiPolygon', coordinates: polys }
  } catch {
    return null
  }
}

/** GeoJSON (Multi)Polygon → Leaflet positions [polygon][ring][[lat, lng]] (optionally unwrapped across ±180°). */
export function leafletPositions(g: AreaGeometry, unwrap = false): LatLng[][][] {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  return polys.map((p) => p.map((r) => r.map(([lon, lat]) => [lat, shiftLon(lon, unwrap)] as LatLng)))
}

// --- Display across the date line ------------------------------------------------

/** Shapes split at ±180° (Fiji, Chukotka…) are drawn on one side by shifting the far-west parts by +360°. */
export function needsUnwrap(g: AreaGeometry): boolean {
  const b = geometryBBox(g)
  if (b.lon_max - b.lon_min <= 180) return false
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  return polys.every((p) => {
    const lons = p[0].map(([lon]) => lon)
    return Math.max(...lons) <= -150 || Math.min(...lons) >= 0
  })
}

export const shiftLon = (lon: number, unwrap: boolean) => (unwrap && lon <= -150 ? lon + 360 : lon)

export function shiftGeometry(g: AreaGeometry, unwrap: boolean): AreaGeometry {
  if (!unwrap) return g
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
  const shifted = polys.map((p) => {
    const west = Math.max(...p[0].map(([lon]) => lon)) <= -150
    return p.map((r) => r.map(([lon, lat]) => [west ? lon + 360 : lon, lat] as Position))
  })
  return g.type === 'Polygon' ? { type: 'Polygon', coordinates: shifted[0] } : { type: 'MultiPolygon', coordinates: shifted }
}
