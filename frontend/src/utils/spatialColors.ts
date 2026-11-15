// Colour scales and per-layer cell styling for the Spatial Trend Explorer.
// Pure functions (unit-tested) — the scale depends only on the analysis result
// and the chosen estimator, never on the map viewport.

import type { SignificanceBasis, SignificanceStatus, SlopeEstimator, SpatialLayer, SpatialTrendCell } from '../types/spatial'

type RGB = [number, number, number]

// Diverging blue–white–red (ColorBrewer RdBu, reversed so red = increase).
const STOPS: RGB[] = [
  [33, 102, 172],  // strong decrease
  [103, 169, 207],
  [240, 240, 240], // zero
  [239, 138, 98],
  [178, 24, 43],   // strong increase
]

const toCss = (c: RGB) => `rgb(${c.map((v) => Math.round(v)).join(', ')})`

/** Colour for a slope on a symmetric scale [-maxAbs, +maxAbs] centred on zero. */
export function divergingColor(value: number, maxAbs: number): string {
  if (!(maxAbs > 0) || !Number.isFinite(value)) return toCss(STOPS[2])
  const t = Math.max(-1, Math.min(1, value / maxAbs)) // -1 … 1
  const pos = (t + 1) * 2 // 0 … 4 across the five stops
  const i = Math.min(3, Math.floor(pos))
  const f = pos - i
  const a = STOPS[i]
  const b = STOPS[i + 1]
  return toCss([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f])
}

/** CSS gradient for the magnitude legend (same stops as divergingColor). */
export const DIVERGING_GRADIENT = `linear-gradient(to right, ${STOPS.map(toCss).join(', ')})`

/** Round a positive number up to 1, 2, 2.5 or 5 × 10^k so legend labels stay readable. */
export function niceCeil(x: number): number {
  if (!(x > 0) || !Number.isFinite(x)) return 0
  const k = Math.floor(Math.log10(x))
  const base = 10 ** k
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (x <= m * base * (1 + 1e-12)) return m * base
  }
  return 10 * base
}

export function slopeOf(cell: SpatialTrendCell, estimator: SlopeEstimator): number | null {
  return estimator === 'sen' ? cell.sen_slope : cell.ols_slope
}

/** Symmetric scale limit: the largest |slope| among analysed cells, rounded up. */
export function symmetricMax(cells: SpatialTrendCell[], estimator: SlopeEstimator): number {
  let m = 0
  for (const c of cells) {
    const s = slopeOf(c, estimator)
    if (s !== null && c.data_status === 'analysed') m = Math.max(m, Math.abs(s))
  }
  return niceCeil(m)
}

export const SIGNIFICANCE_COLORS: Record<SignificanceStatus, string> = {
  significant_increasing: '#c2410c',
  significant_decreasing: '#1d4ed8',
  not_significant: '#cbd5e1',
  insufficient_data: '#0a1322',
  not_testable: '#6b5b95',
  excluded: '#334155',
}

export const SIGNIFICANCE_LABELS: Record<SignificanceStatus, string> = {
  significant_increasing: 'Significant increase',
  significant_decreasing: 'Significant decrease',
  not_significant: 'Not statistically significant',
  insufficient_data: 'Insufficient data',
  not_testable: 'Not testable (no variation, failed or no p-value)',
  excluded: 'Excluded (water or ice for a land-only variable)',
}

export const DIRECTION_COLORS = { increasing: '#ef8a62', decreasing: '#67a9cf', near_zero: '#f0f0f0' } as const
export const DIRECTION_LABELS = { increasing: 'Increasing slope', decreasing: 'Decreasing slope', near_zero: 'Near zero' } as const

export const AVAILABILITY_COLORS = {
  complete: '#2dd4bf',
  partial: '#fbbf24',
  insufficient: '#f97316',
  missing: '#b91c1c',
  excluded: '#334155',
} as const
export const AVAILABILITY_LABELS = {
  complete: 'Complete record',
  partial: 'Some months missing (still analysed)',
  insufficient: 'Too few usable years',
  missing: 'No valid data',
  excluded: 'Excluded (water or ice)',
} as const

export interface DisplayOptions {
  layer: SpatialLayer
  estimator: SlopeEstimator
  basis: SignificanceBasis
  maxAbs: number
  showGrid: boolean
  showMissing: boolean
  showNonSignificant: boolean
}

export interface CellStyle {
  visible: boolean
  fillColor: string
  fillOpacity: number
  color: string
  weight: number
  dashArray?: string
}

export function statusOf(cell: SpatialTrendCell, basis: SignificanceBasis): SignificanceStatus {
  return basis === 'raw' ? cell.raw_status : cell.status
}

const isSignificant = (s: SignificanceStatus) => s === 'significant_increasing' || s === 'significant_decreasing'

/** Style of one cell for the active layer. Hidden cells stay in every calculation; only the drawing changes. */
export function cellStyle(cell: SpatialTrendCell, o: DisplayOptions): CellStyle {
  const status = statusOf(cell, o.basis)
  const noData = cell.data_status !== 'analysed'
  const gridStroke = o.showGrid ? 0.5 : 0
  const base: CellStyle = { visible: true, fillColor: '#0a1322', fillOpacity: 0.15, color: '#0a1322', weight: gridStroke }

  if (o.layer === 'availability') {
    const excluded = cell.availability === 'excluded'
    if (!o.showMissing && cell.availability !== 'complete' && cell.availability !== 'partial') return { ...base, visible: false }
    return { ...base, fillColor: AVAILABILITY_COLORS[cell.availability], fillOpacity: excluded ? 0.35 : 0.7, dashArray: excluded ? '2 3' : undefined }
  }

  if (noData) {
    if (!o.showMissing) return { ...base, visible: false }
    const excluded = cell.data_status === 'excluded'
    return {
      ...base,
      fillColor: excluded ? SIGNIFICANCE_COLORS.excluded : '#0a1322',
      fillOpacity: excluded ? 0.35 : 0.25,
      color: excluded ? '#7189a8' : '#fbbf24',
      weight: 1.2,
      dashArray: excluded ? '2 3' : '4 3',
    }
  }

  const sig = isSignificant(status)
  if (!sig && !o.showNonSignificant) {
    // Shown as an outline only — still part of the correction family and the summary.
    return { ...base, fillOpacity: 0, color: '#64748b', weight: Math.max(gridStroke, 0.6) }
  }

  // Significant cells get a dark outline on the magnitude and direction layers (like stippling).
  const outline = sig && o.layer !== 'significance' ? { color: '#0b1220', weight: 2 } : {}

  if (o.layer === 'magnitude') {
    const s = slopeOf(cell, o.estimator)
    return { ...base, fillColor: s === null ? '#0a1322' : divergingColor(s, o.maxAbs), fillOpacity: 0.8, ...outline }
  }
  if (o.layer === 'direction') {
    const d = o.estimator === 'sen' ? cell.direction_sen : cell.direction_ols
    return { ...base, fillColor: d ? DIRECTION_COLORS[d] : '#0a1322', fillOpacity: 0.8, ...outline }
  }
  // significance
  return {
    ...base,
    fillColor: SIGNIFICANCE_COLORS[status],
    fillOpacity: sig ? 0.8 : 0.45,
  }
}
