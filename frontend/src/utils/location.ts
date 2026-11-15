import type { Place } from '../types/api'
import { parseCoordinate, validateLatitude, validateLongitude } from './validation'

/** "Name, Region, Country" without repeats; coordinates results show just the pair. */
export function placeLabel(p: Place): string {
  if (p.place_type === 'coordinates') return p.name
  const parts = [p.name, p.region, p.country].filter((x, i, arr): x is string => Boolean(x) && arr.indexOf(x) === i)
  return parts.join(', ')
}

export interface LocationValue {
  latText: string
  lonText: string
  /** Name from search or a preset. Cleared when the point is moved by hand. */
  placeName: string | null
}

export const EMPTY_LOCATION: LocationValue = { latText: '', lonText: '', placeName: null }

/** Parsed, validated coordinates of a LocationValue (or null if invalid/empty). */
export function parseLocation(v: LocationValue): { lat: number; lon: number } | null {
  const lat = parseCoordinate(v.latText)
  const lon = parseCoordinate(v.lonText)
  if (validateLatitude(lat) || validateLongitude(lon) || lat === null || lon === null) return null
  return { lat, lon }
}
