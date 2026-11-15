import { useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SeriesView } from '../../types/api'
import { formatNumber, monthName } from '../../utils/format'

// Validated (CVD separation + contrast) against the surface chart surface.
const OBSERVED = 'var(--color-series-observed)'
const TREND = 'var(--color-series-trend)'
const EXCLUDED = 'var(--color-fg-subtle)'
const BAND = 'rgba(14, 165, 198, 0.16)'
const GRID = 'var(--color-chart-grid)'
const AXIS = 'var(--color-chart-axis)'

type View = 'monthly' | 'annual'

interface Row {
  t: number
  label: string
  value: number | null
  excluded?: number | null
  trend?: number
  /** Regional only: mean ± 1 SD across grid cells (spatial variability). */
  band?: [number, number] | null
  sd?: number | null
  note: string
}

function ToggleGroup<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-line-strong bg-sunken p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            value === o.value ? 'bg-accent/15 text-accent' : 'text-fg-muted hover:text-fg'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function ChartTooltip({
  active,
  payload,
  unit,
}: {
  active?: boolean
  payload?: { payload: Row }[]
  unit: string
}) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const shown = row.value ?? row.excluded ?? null
  return (
    <div className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm shadow-xl">
      <p className="font-semibold text-fg">{row.label}</p>
      <p className="mt-1 flex items-center gap-2 text-fg-muted">
        <span className="inline-block h-0.5 w-3" style={{ background: row.value !== null ? OBSERVED : EXCLUDED }} />
        {shown === null ? 'No valid data' : `${formatNumber(shown, 4)} ${unit}`}
      </p>
      {row.sd != null && row.value !== null && (
        <p className="text-xs text-fg-muted">Spatial SD across cells: ±{formatNumber(row.sd, 3)} {unit}</p>
      )}
      {row.trend !== undefined && (
        <p className="flex items-center gap-2 text-fg-muted">
          <span className="inline-block w-3 border-t-2 border-dashed" style={{ borderColor: TREND }} />
          Trend: {formatNumber(row.trend, 4)} {unit}
        </p>
      )}
      <p className="mt-1 text-xs text-fg-subtle">{row.note}</p>
    </div>
  )
}

const MONTH_NOTE: Record<string, string> = {
  valid: 'Monthly mean (NASA POWER)',
  invalid: 'Invalid value removed',
  missing: 'Missing in NASA POWER',
  insufficient_coverage: 'Too few valid grid cells — excluded',
}

export function TimeSeriesChart({ result }: { result: SeriesView }) {
  const [view, setView] = useState<View>('annual')
  const [showTrend, setShowTrend] = useState(true)
  const hasSpread = result.monthly.some((m) => m.spatial_sd != null)
  const [showBand, setShowBand] = useState(true)
  const unit = result.metadata.unit_display
  const stats = result.statistics
  const reg = stats?.regression

  const rows = useMemo<Row[]>(() => {
    const base: Row[] =
      view === 'monthly'
        ? result.monthly.map((m) => ({
            t: m.year + (m.month - 0.5) / 12,
            label: `${monthName(m.month)} ${m.year}`,
            value: m.value,
            sd: m.spatial_sd ?? null,
            band: m.value !== null && m.spatial_sd != null ? ([m.value - m.spatial_sd, m.value + m.spatial_sd] as [number, number]) : null,
            note: hasSpread && m.status === 'valid' ? 'Area-weighted regional mean (NASA POWER)' : (MONTH_NOTE[m.status] ?? m.status),
          }))
        : result.annual.map((a) => ({
            t: a.year + 0.5,
            label: String(a.year),
            value: a.used_in_trend ? a.value : null,
            excluded: !a.used_in_trend ? a.value : null,
            sd: a.spatial_sd ?? null,
            band: a.used_in_trend && a.value !== null && a.spatial_sd != null ? ([a.value - a.spatial_sd, a.value + a.spatial_sd] as [number, number]) : null,
            note: a.used_in_trend
              ? `Day-weighted annual mean · ${a.valid_months}/12 months`
              : a.value === null
                ? 'No valid months'
                : `Excluded from trend tests · only ${a.valid_months}/12 months`,
          }))
    if (!reg || !stats || !showTrend) return base
    // Regression was fitted on x = year (annual means centred mid-year), so trend(t) = a + b·(t − 0.5).
    return base.map((r) =>
      r.t >= stats.first_year && r.t <= stats.last_year + 1
        ? { ...r, trend: reg.intercept + reg.slope * (r.t - 0.5) }
        : r,
    )
  }, [view, result, reg, stats, showTrend, hasSpread])

  const startYear = result.metadata.start_year
  const endYear = result.metadata.end_year
  const span = endYear - startYear + 1
  const step = span > 30 ? 5 : span > 15 ? 2 : 1
  const ticks = Array.from({ length: Math.floor(span / step) + 1 }, (_, i) => startYear + i * step).filter((y) => y <= endYear + 1)
  const hasExcluded = view === 'annual' && result.annual.some((a) => !a.used_in_trend && a.value !== null)
  const missingMonths = result.summary.n_monthly_missing

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <ToggleGroup
          label="Time resolution"
          value={view}
          onChange={setView}
          options={[
            { value: 'annual', label: 'Annual averages' },
            { value: 'monthly', label: 'Monthly' },
          ]}
        />
        <label className={`inline-flex items-center gap-2 text-sm ${reg ? 'text-fg-muted' : 'text-fg-subtle'}`}>
          <input
            type="checkbox"
            className="size-4 accent-[var(--color-series-trend)]"
            checked={showTrend && Boolean(reg)}
            disabled={!reg}
            onChange={(e) => setShowTrend(e.target.checked)}
          />
          Show regression trend line
        </label>
        {hasSpread && (
          <label className="inline-flex items-center gap-2 text-sm text-fg-muted">
            <input type="checkbox" className="size-4 accent-[var(--color-series-observed)]" checked={showBand} onChange={(e) => setShowBand(e.target.checked)} />
            Show spatial variability band
          </label>
        )}
      </div>

      {/* Legend (identity is never colour-only: line style + text) */}
      <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-fg-muted" aria-label="Chart legend">
        <li className="flex items-center gap-2">
          <span className="inline-block h-0.5 w-5 rounded" style={{ background: OBSERVED }} />
          {view === 'annual' ? 'Annual mean (used in trend tests)' : 'Monthly mean'}
        </li>
        {reg && showTrend && (
          <li className="flex items-center gap-2">
            <span className="inline-block w-5 border-t-2 border-dashed" style={{ borderColor: TREND }} />
            Linear regression trend
          </li>
        )}
        {hasExcluded && (
          <li className="flex items-center gap-2">
            <span className="inline-block size-2.5 rounded-full border-2" style={{ borderColor: EXCLUDED }} />
            Incomplete year (excluded)
          </li>
        )}
        {hasSpread && showBand && (
          <li className="flex items-center gap-2">
            <span className="inline-block h-3 w-5 rounded-sm" style={{ background: BAND }} />
            Spatial variability: ±1 SD across grid cells (not a confidence interval)
          </li>
        )}
      </ul>

      <div className="h-[340px] w-full sm:h-[400px]" role="img" aria-label={`${result.metadata.variable_name} time series chart, ${view} view`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[startYear, endYear + 1]}
              ticks={ticks}
              tickFormatter={(v: number) => String(Math.floor(v))}
              stroke={AXIS}
              tick={{ fill: AXIS, fontSize: 12 }}
              tickLine={false}
              axisLine={{ stroke: GRID }}
              label={{ value: 'Year', position: 'insideBottom', offset: -16, fill: AXIS, fontSize: 12 }}
            />
            <YAxis
              domain={['auto', 'auto']}
              stroke={AXIS}
              tick={{ fill: AXIS, fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={64}
              tickFormatter={(v: number) => formatNumber(v, 3)}
              label={{
                value: `${result.metadata.variable_name} · ${unit}`,
                angle: -90,
                position: 'insideLeft',
                offset: 4,
                fill: AXIS,
                fontSize: 12,
                style: { textAnchor: 'middle' },
              }}
            />
            <Tooltip
              content={<ChartTooltip unit={unit} />}
              cursor={{ stroke: AXIS, strokeDasharray: '3 3' }}
              isAnimationActive={false}
            />
            {hasSpread && showBand && (
              <Area type="linear" dataKey="band" stroke="none" fill={BAND} connectNulls={false} isAnimationActive={false} name="Spatial ±1 SD" activeDot={false} />
            )}
            <Line
              type="linear"
              dataKey="value"
              stroke={OBSERVED}
              strokeWidth={2}
              dot={view === 'annual' ? { r: 4, fill: OBSERVED, stroke: 'var(--color-surface)', strokeWidth: 2 } : false}
              activeDot={{ r: 5, stroke: 'var(--color-surface)', strokeWidth: 2 }}
              connectNulls={false}
              isAnimationActive={false}
              name="Observed"
            />
            {hasExcluded && (
              <Scatter dataKey="excluded" fill="var(--color-surface)" stroke={EXCLUDED} strokeWidth={2} isAnimationActive={false} name="Excluded" />
            )}
            {reg && showTrend && (
              <Line
                type="linear"
                dataKey="trend"
                stroke={TREND}
                strokeWidth={2}
                strokeDasharray="7 5"
                dot={false}
                activeDot={false}
                isAnimationActive={false}
                name="Trend"
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-fg-subtle">
        {missingMonths > 0
          ? `${missingMonths} month(s) have no valid ${hasSpread ? 'regional mean (too little valid area or no data)' : 'NASA value'} and are shown as gaps — they are never filled with zero or interpolated.`
          : 'All months in this period have valid NASA values.'}{' '}
        {hasSpread && showBand && 'The shaded band shows how much grid cells differ from each other (spatial variability); it is not the uncertainty of the trend. '}
        {view === 'monthly' && 'The monthly view includes the seasonal cycle; trend tests use annual averages.'}
      </p>
    </div>
  )
}
