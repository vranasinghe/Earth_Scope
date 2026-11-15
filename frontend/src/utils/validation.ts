export interface YearLimits {
  minYear: number
  maxYear: number
  minSpan: number
}

export function parseCoordinate(raw: string): number | null {
  const trimmed = raw.trim()
  if (trimmed === '' || !/^[-+]?\d*\.?\d+$/.test(trimmed)) return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

export function validateLatitude(lat: number | null): string | null {
  if (lat === null) return 'Enter a latitude as a decimal number (e.g. 40.7128 or -33.8688).'
  if (lat < -90 || lat > 90) return 'Latitude must be between -90 and 90.'
  return null
}

export function validateLongitude(lon: number | null): string | null {
  if (lon === null) return 'Enter a longitude as a decimal number (e.g. -74.0060 or 151.2093).'
  if (lon < -180 || lon > 180) return 'Longitude must be between -180 and 180.'
  return null
}

export function validateYears(start: number, end: number, limits: YearLimits): string | null {
  if (!Number.isInteger(start) || !Number.isInteger(end)) return 'Years must be whole numbers.'
  if (start < limits.minYear || end > limits.maxYear) {
    return `Years must be between ${limits.minYear} and ${limits.maxYear}.`
  }
  if (start >= end) return 'The start year must be earlier than the end year.'
  const span = end - start + 1
  if (span < limits.minSpan) {
    return `Select at least ${limits.minSpan} years (currently ${span}). Trend tests need a reasonably long record.`
  }
  return null
}
