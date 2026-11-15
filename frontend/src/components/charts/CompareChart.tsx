import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { COMPARE_SERIES } from '../../constants/compare'
import type { CompareResponse } from '../../types/api'
import { formatNumber, formatSigned } from '../../utils/format'

const GRID = 'var(--color-chart-grid)'
const AXIS = 'var(--color-chart-axis)'

type View = 'anomaly' | 'absolute'

interface Row {
  year: number
  [key: string]: number | null
}

function CompareTooltip({
  active,
  payload,
  label,
  names,
  unit,
  view,
}: {
  active?: boolean
  payload?: { dataKey: string; value: number | null }[]
  label?: number
  names: string[]
  unit: string
  view: View
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-sm shadow-xl">
      <p className="font-semibold text-fg">{label}</p>
      {payload.map((p) => {
        const i = Number(p.dataKey.slice(1))
        return (
          <p key={p.dataKey} className="mt-1 flex items-center gap-2 text-fg-muted">
            <svg width="18" height="6" aria-hidden>
              <line x1="0" y1="3" x2="18" y2="3" stroke={COMPARE_SERIES[i].color} strokeWidth="2" strokeDasharray={COMPARE_SERIES[i].dash} />
            </svg>
            {names[i]}: {p.value === null ? 'no data' : `${view === 'anomaly' ? formatSigned(p.value, 3) : formatNumber(p.value, 4)} ${unit}`}
          </p>
        )
      })}
    </div>
  )
}

/** Annual means for up to three locations; optional "difference from own period mean" view. */
export function CompareChart({ result }: { result: CompareResponse }) {
  const [view, setView] = useState<View>('anomaly')
  const series = useMemo(
    () => result.locations.map((loc, i) => ({ loc, i })).filter(({ loc }) => loc.ok && loc.annual.length > 0),
    [result.locations],
  )
  const names = result.locations.map((l) => l.label)

  const rows = useMemo<Row[]>(() => {
    const means = series.map(({ loc }) => {
      const used = loc.annual.filter((a) => a.used_in_trend && a.value !== null).map((a) => a.value as number)
      return used.length ? used.reduce((s, v) => s + v, 0) / used.length : 0
    })
    const out: Row[] = []
    for (let y = result.start_year; y <= result.end_year; y++) {
      const row: Row = { year: y }
      series.forEach(({ loc, i }, k) => {
        const a = loc.annual.find((r) => r.year === y)
        const v = a && a.used_in_trend && a.value !== null ? a.value : null
        row[`s${i}`] = v === null ? null : view === 'anomaly' ? v - means[k] : v
      })
      out.push(row)
    }
    return out
  }, [series, result.start_year, result.end_year, view])

  if (series.length === 0) return <p className="text-sm text-fg-muted">No location returned usable data to chart.</p>

  const unit = result.unit_display
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Chart values" className="inline-flex rounded-lg border border-line-strong bg-sunken p-0.5">
          {(
            [
              ['anomaly', 'Change vs own average'],
              ['absolute', 'Absolute values'],
            ] as const
          ).map(([v, label]) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                view === v ? 'bg-accent/15 text-accent' : 'text-fg-muted hover:text-fg'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-sm text-fg-muted" aria-label="Chart legend">
        {series.map(({ loc, i }) => (
          <li key={i} className="flex items-center gap-2">
            <svg width="24" height="6" aria-hidden>
              <line x1="0" y1="3" x2="24" y2="3" stroke={COMPARE_SERIES[i].color} strokeWidth="2.5" strokeDasharray={COMPARE_SERIES[i].dash} />
            </svg>
            {i + 1}. {loc.label} <span className="text-fg-subtle">({COMPARE_SERIES[i].dashLabel})</span>
          </li>
        ))}
      </ul>
      <div className="h-[340px] w-full sm:h-[380px]" role="img" aria-label={`${result.variable_name} comparison chart`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 28, left: 8 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="year"
              type="number"
              domain={[result.start_year, result.end_year]}
              allowDecimals={false}
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
              tickFormatter={(v: number) => (view === 'anomaly' ? formatSigned(v, 2) : formatNumber(v, 3))}
              label={{
                value: view === 'anomaly' ? `Difference from own mean · ${unit}` : `Annual mean · ${unit}`,
                angle: -90,
                position: 'insideLeft',
                offset: 4,
                fill: AXIS,
                fontSize: 12,
                style: { textAnchor: 'middle' },
              }}
            />
            {view === 'anomaly' && <ReferenceLine y={0} stroke={AXIS} strokeOpacity={0.5} />}
            <Tooltip content={<CompareTooltip names={names} unit={unit} view={view} />} cursor={{ stroke: AXIS, strokeDasharray: '3 3' }} isAnimationActive={false} />
            {series.map(({ i }) => (
              <Line
                key={i}
                type="linear"
                dataKey={`s${i}`}
                stroke={COMPARE_SERIES[i].color}
                strokeWidth={2}
                strokeDasharray={COMPARE_SERIES[i].dash}
                dot={{ r: 3, fill: COMPARE_SERIES[i].color, stroke: 'var(--color-surface)', strokeWidth: 1.5 }}
                activeDot={{ r: 5, stroke: 'var(--color-surface)', strokeWidth: 2 }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-xs text-fg-subtle">
        {view === 'anomaly'
          ? 'Each line shows how a location’s annual mean differs from its own average over the period, so their slopes (trends) can be compared directly. Absolute levels are not compared in this view.'
          : 'Absolute annual means. A higher line means a higher level, not a faster change — compare trends using the table or the “change vs own average” view.'}{' '}
        Years with fewer than {result.locations.find((l) => l.summary)?.summary?.min_valid_months_per_year ?? 10} valid months
        are left as gaps.
      </p>
    </div>
  )
}
