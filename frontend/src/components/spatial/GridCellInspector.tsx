import { Download, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis } from 'recharts'
import { useSpatialCell } from '../../hooks/useSpatialTrends'
import type { RegionalMetadata } from '../../types/api'
import type { SpatialCellParams, SpatialTrendCell } from '../../types/spatial'
import { formatNumber, formatP, formatSigned } from '../../utils/format'
import { SIGNIFICANCE_LABELS } from '../../utils/spatialColors'
import { downloadCellSeries } from '../../utils/spatialExport'
import { ErrorState } from '../common/States'

const CELL = 'var(--color-series-observed)'
const TREND = 'var(--color-series-trend)'
const REGION = 'var(--color-series-region)'
const GRID = 'var(--color-chart-grid)'
const AXIS = 'var(--color-chart-axis)'

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 border-b border-raised py-1 text-xs last:border-0">
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="stat-num text-right text-fg">{children}</dd>
    </div>
  )
}

interface Props {
  params: SpatialCellParams
  cell: SpatialTrendCell
  metadata: RegionalMetadata
  onClose: () => void
}

export function GridCellInspector({ params, cell: c, metadata: m, onClose }: Props) {
  const { data, error, loading, retry } = useSpatialCell(params)
  const [showRegional, setShowRegional] = useState(true)
  const panel = useRef<HTMLElement>(null)
  // Below the lg breakpoint the inspector sits under the map: bring it into view when a cell is chosen.
  useEffect(() => {
    if (window.innerWidth < 1024) panel.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [])
  const unit = m.unit_display
  const rows = useMemo(() => {
    if (!data) return []
    const reg = new Map((data.regional_annual ?? []).map((a) => [a.year, a.used_in_trend ? a.value : null]))
    return data.annual.map((a) => ({
      year: a.year,
      value: a.used_in_trend ? a.value : null,
      excluded: !a.used_in_trend && a.value !== null ? a.value : null,
      trend: a.used_in_trend && c.ols_slope !== null && c.ols_intercept !== null ? c.ols_intercept + c.ols_slope * a.year : null,
      regional: reg.get(a.year) ?? null,
      months: a.valid_months,
    }))
  }, [data, c.ols_slope, c.ols_intercept])
  const hasRegional = rows.some((r) => r.regional !== null)

  return (
    <aside ref={panel} className="card card-pad min-w-0 scroll-mt-24" aria-label={`Grid cell ${c.id} details`}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <h3 className="font-bold">Grid cell {c.latitude}°, {c.longitude}°</h3>
          <p className="font-mono text-[11px] text-fg-subtle">id {c.id}</p>
        </div>
        <button type="button" className="btn-ghost p-1.5" onClick={onClose} aria-label="Close cell details">
          <X className="size-4" aria-hidden />
        </button>
      </div>

      <p className={`mb-3 rounded-lg px-2.5 py-1.5 text-xs font-semibold ${c.status.startsWith('significant') ? 'bg-accent/15 text-accent' : 'bg-raised text-fg-muted'}`}>
        {SIGNIFICANCE_LABELS[c.status]}
        {c.status_reason ? ` — ${c.status_reason}` : ''}
      </p>

      <dl>
        <Row label="Bounds">{c.lat_min}…{c.lat_max}° lat, {c.lon_min}…{c.lon_max}° lon</Row>
        <Row label="Grid resolution">0.5° × 0.625° (MERRA-2)</Row>
        <Row label="Inside the region">{(c.overlap_fraction * 100).toFixed(0)}% · {formatNumber(c.overlap_area_km2, 4)} km² · weight {(c.weight * 100).toFixed(2)}%</Row>
        <Row label="Variable">{m.variable_name} ({m.parameter}), {unit}</Row>
        <Row label="Valid observations">{c.valid_months}/{c.total_months} months · {c.valid_years}/{c.total_years} years</Row>
        <Row label="Source">{`NASA POWER (${m.sources.join(', ')})`}</Row>
        {c.data_status === 'analysed' && (
          <>
            <Row label="OLS slope">{formatSigned(c.ols_slope)} {m.rate_unit}</Row>
            <Row label="OLS p · R²">{formatP(c.ols_p_value)} · {formatNumber(c.ols_r_squared, 3)}</Row>
            <Row label="Sen’s slope">{formatSigned(c.sen_slope)} {m.rate_unit}</Row>
            <Row label="Sen 95% CI">{formatSigned(c.sen_ci_lower)} to {formatSigned(c.sen_ci_upper)}</Row>
            <Row label="Mann-Kendall p">{formatP(c.mk_p_value)}</Row>
            <Row label="Hamed–Rao p (canonical / conservative)">{formatP(c.hr_canonical_p_value)} / {formatP(c.hr_conservative_p_value)}</Row>
            <Row label="Yue–Wang p (canonical)">{formatP(c.yw_canonical_p_value)}</Row>
            <Row label="Selected test p">{formatP(c.raw_p_value)}</Row>
            <Row label="Adjusted p (q)">{c.adjusted_p_value === null ? 'no correction' : formatP(c.adjusted_p_value)}</Row>
            <Row label="Lag-1 autocorrelation">{formatNumber(c.lag1_autocorrelation, 2)}{c.ljung_box_p_value !== null ? ` · Ljung–Box p ${formatP(c.ljung_box_p_value)}` : ''}</Row>
          </>
        )}
      </dl>

      <div className="mt-4">
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <h4 className="text-sm font-semibold">Annual series</h4>
          {hasRegional && (
            <label className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
              <input type="checkbox" checked={showRegional} onChange={() => setShowRegional((v) => !v)} /> Compare with regional aggregate
            </label>
          )}
        </div>
        {loading && <p className="py-10 text-center text-xs text-fg-muted" role="status">Loading cell series…</p>}
        {error && <ErrorState error={error} title="Could not load this cell" onRetry={retry} />}
        {data && (
          <>
            <div className="h-56 w-full" role="img" aria-label={`Annual ${m.variable_name} at cell ${c.id}`}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 6, right: 8, bottom: 4, left: 0 }}>
                  <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
                  <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} stroke={AXIS} tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={{ stroke: GRID }} />
                  <YAxis domain={['auto', 'auto']} stroke={AXIS} tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={48} tickFormatter={(v: number) => formatNumber(v, 3)} />
                  <Tooltip
                    contentStyle={{ background: 'var(--color-surface)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                    formatter={(v, name) => [v === null || v === undefined ? '—' : `${formatNumber(Number(v), 4)} ${unit}`, String(name)]}
                    labelFormatter={(l) => String(l)}
                    isAnimationActive={false}
                  />
                  <Line type="linear" dataKey="value" name="Selected grid cell" stroke={CELL} strokeWidth={2} dot={{ r: 2.5, fill: CELL }} connectNulls={false} isAnimationActive={false} />
                  <Scatter dataKey="excluded" name="Incomplete year (not used)" fill="var(--color-surface)" stroke="var(--color-fg-subtle)" strokeWidth={2} isAnimationActive={false} />
                  {c.ols_slope !== null && <Line type="linear" dataKey="trend" name="OLS trend (cell)" stroke={TREND} strokeWidth={2} strokeDasharray="6 4" dot={false} activeDot={false} isAnimationActive={false} />}
                  {showRegional && hasRegional && (
                    <Line type="linear" dataKey="regional" name="Regional aggregate" stroke={REGION} strokeWidth={1.5} strokeDasharray="2 3" dot={false} connectNulls={false} isAnimationActive={false} />
                  )}
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted">
              <li><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: CELL }} />Selected grid cell (annual mean, {unit})</li>
              {c.ols_slope !== null && <li><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: TREND }} />OLS trend</li>}
              {showRegional && hasRegional && <li><span className="mr-1 inline-block h-0.5 w-4 align-middle" style={{ background: REGION }} />Regional aggregate (area-weighted mean, same years and annual rule)</li>}
            </ul>
            <p className="mt-1 text-[11px] text-fg-subtle">Gaps are years with too few valid months; they are never filled. The regional line only shows years that passed its own coverage rule.</p>
            <button type="button" className="btn-secondary mt-3 w-full justify-center py-2 text-xs" onClick={() => downloadCellSeries(data)}>
              <Download className="size-4" aria-hidden /> Download this cell’s annual series (CSV)
            </button>
          </>
        )}
      </div>
    </aside>
  )
}
