const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function monthName(month: number): string {
  return MONTHS[month - 1] ?? String(month)
}

/** Format to `sig` significant digits without scientific notation for typical magnitudes. */
export function formatNumber(value: number | null | undefined, sig = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (value === 0) return '0'
  const abs = Math.abs(value)
  if (abs >= 1e-4 && abs < 1e6) {
    return Number(value.toPrecision(sig)).toString()
  }
  return value.toExponential(sig - 1)
}

export function formatSigned(value: number | null | undefined, sig = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  const s = formatNumber(value, sig)
  return value > 0 ? `+${s}` : s
}

export function formatFixed(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(decimals)
}

export function formatP(p: number | null | undefined): string {
  if (p === null || p === undefined || !Number.isFinite(p)) return '—'
  if (p < 0.001) return '< 0.001'
  return p.toFixed(3)
}

/** "p = 0.023" or "p < 0.001" (never "p = < 0.001"). */
export function formatPExpr(p: number | null | undefined): string {
  const s = formatP(p)
  return s.startsWith('<') ? `p ${s}` : `p = ${s}`
}

export function formatCoord(lat: number, lon: number, decimals = 4): string {
  const ns = lat >= 0 ? 'N' : 'S'
  const ew = lon >= 0 ? 'E' : 'W'
  return `${Math.abs(lat).toFixed(decimals)}° ${ns}, ${Math.abs(lon).toFixed(decimals)}° ${ew}`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Decimals that suit a variable's typical magnitude in tables. */
export function decimalsFor(parameter: string): number {
  return parameter === 'GWETTOP' ? 3 : 2
}
