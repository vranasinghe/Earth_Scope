// Analysis settings are kept in the URL (/results?variable=...&lat=...) so a
// result can be bookmarked, shared, refreshed, or edited from the Explore page.

import { findPreset, presetLabel } from '../constants/locations'
import type { AnalysisParams, CompareParams } from '../types/api'

export function toSearch(p: AnalysisParams): string {
  const q = new URLSearchParams({
    variable: p.variable,
    lat: String(p.latitude),
    lon: String(p.longitude),
    start: String(p.startYear),
    end: String(p.endYear),
  })
  if (p.place) q.set('place', p.place)
  return `?${q.toString()}`
}

export function fromSearch(search: URLSearchParams): AnalysisParams | null {
  const variable = search.get('variable')
  const latitude = Number(search.get('lat'))
  const longitude = Number(search.get('lon'))
  const startYear = Number(search.get('start'))
  const endYear = Number(search.get('end'))
  if (!variable || ![search.get('lat'), search.get('lon'), search.get('start'), search.get('end')].every((v) => v !== null && v !== '')) {
    return null
  }
  if (![latitude, longitude, startYear, endYear].every(Number.isFinite)) return null
  const place = search.get('place')?.slice(0, 120) || undefined
  return { variable, latitude, longitude, startYear, endYear, place }
}

/** Display name for a point: explicit name, else a matching preset, else undefined. */
export function knownPlaceName(lat: number, lon: number, explicit?: string): string | undefined {
  if (explicit) return explicit
  const p = findPreset(lat, lon)
  return p ? presetLabel(p) : undefined
}

// --- Comparison URLs: /compare?variable=...&loc=lat,lon,label&loc=... ----------

export function toCompareSearch(p: CompareParams): string {
  const q = new URLSearchParams({ variable: p.variable, start: String(p.startYear), end: String(p.endYear) })
  for (const l of p.locations) q.append('loc', `${l.latitude},${l.longitude},${l.label}`)
  return `?${q.toString()}`
}

export function fromCompareSearch(search: URLSearchParams): CompareParams | null {
  const variable = search.get('variable')
  const startYear = Number(search.get('start'))
  const endYear = Number(search.get('end'))
  const locations = search
    .getAll('loc')
    .map((raw) => {
      const [la, lo, ...rest] = raw.split(',')
      const latitude = Number(la)
      const longitude = Number(lo)
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || la === '' || lo === '') return null
      return { latitude, longitude, label: rest.join(',').trim().slice(0, 80) || `${latitude}, ${longitude}` }
    })
    .filter((x): x is { latitude: number; longitude: number; label: string } => x !== null)
  if (!variable || !Number.isFinite(startYear) || !Number.isFinite(endYear) || locations.length < 2) return null
  return { variable, startYear, endYear, locations }
}
