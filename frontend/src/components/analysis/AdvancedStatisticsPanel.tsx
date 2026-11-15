import { AlertTriangle, CheckCircle2, CircleSlash, Scale } from 'lucide-react'
import type { ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { HELP } from '../../constants/advancedHelp'
import type { Interpretation, ModifiedMannKendallResult, StatisticsResult } from '../../types/api'
import { formatNumber, formatP, formatPExpr, formatSigned } from '../../utils/format'
import { InfoTip } from '../common/InfoTip'

const INSIDE = 'var(--color-series-observed)'
const OUTSIDE = 'var(--color-series-trend)'
const GRID = 'var(--color-chart-grid)'
const AXIS = 'var(--color-chart-axis)'

function Card({ title, help, children, className = '' }: { title: string; help?: string; children: ReactNode; className?: string }) {
  return (
    // min-w-0 lets grid children shrink so wide tables scroll inside their card on phones.
    <section className={`card card-pad min-w-0 ${className}`}>
      <h3 className="flex items-center font-semibold">
        {title}
        {help && <InfoTip label={title} text={help} />}
      </h3>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Decision({ significant }: { significant: boolean | null }) {
  if (significant === null) return <span className="text-fg-subtle">Not available</span>
  return significant ? (
    <span className="inline-flex items-center gap-1 text-teal">
      <CheckCircle2 className="size-3.5" aria-hidden /> Significant
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-fg-muted">
      <CircleSlash className="size-3.5" aria-hidden /> Not significant
    </span>
  )
}

function MkComparison({ stats }: { stats: StatisticsResult }) {
  const orig = stats.mann_kendall
  const hr = stats.advanced!.modified_mann_kendall
  const yw = stats.advanced!.yue_wang_sensitivity
  const rows: { label: string; help?: string; a: ReactNode; b: ReactNode }[] = [
    { label: 'Trend direction', a: orig.trend, b: hr.trend ?? '—' },
    { label: 'S statistic', a: formatNumber(orig.s, 4), b: formatNumber(hr.s, 4) },
    { label: 'Variance of S', a: formatNumber(orig.var_s, 5), b: hr.var_s === null ? '—' : formatNumber(hr.var_s, 5) },
    { label: 'Z statistic', a: orig.z.toFixed(3), b: hr.z === null ? '—' : hr.z.toFixed(3) },
    { label: 'p-value', a: formatP(orig.p_value), b: formatP(hr.p_value) },
    { label: `Decision (α = ${stats.alpha})`, a: <Decision significant={orig.significant} />, b: <Decision significant={hr.significant} /> },
    {
      label: 'Variance correction factor',
      a: '1 (none)',
      b: hr.reduction_suppressed
        ? `1.000 (estimated ${hr.raw_correction_factor.toFixed(2)}; reductions not applied)`
        : hr.correction_factor.toFixed(3),
    },
    { label: 'Effective number of years', help: HELP.effectiveN, a: String(orig.n), b: hr.effective_n === null ? '—' : hr.effective_n.toFixed(1) },
    {
      label: 'Canonical Hamed–Rao p (no floor)',
      help: HELP.canonical,
      a: '—',
      b:
        hr.canonical_p_value === null
          ? 'not computable'
          : `${formatP(hr.canonical_p_value)} (${hr.canonical_significant ? 'significant' : 'not significant'})`,
    },
  ]
  return (
    <Card title="Mann-Kendall: original vs autocorrelation-adjusted" className="lg:col-span-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-sm text-fg-subtle">
              <th scope="col" className="py-2 pr-3 font-semibold">Statistic</th>
              <th scope="col" className="py-2 pr-3 font-semibold">
                Original <InfoTip label="Original Mann-Kendall" text={HELP.originalMk} />
              </th>
              <th scope="col" className="py-2 font-semibold">
                Modified (Hamed–Rao, conservative) <InfoTip label="Hamed–Rao modified test" text={HELP.modifiedMk} />
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-line/50 last:border-0">
                <th scope="row" className="py-2 pr-3 text-left font-normal text-fg-muted">
                  {r.label}
                  {r.help && <InfoTip label={r.label} text={r.help} />}
                </th>
                <td className="stat-num py-2 pr-3 text-fg">{r.a}</td>
                <td className="stat-num py-2 text-fg">{r.b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-fg-muted">
        {!hr.available
          ? hr.unavailable_reason
          : hr.correction_applied
            ? `Significant positive rank autocorrelation at lag(s) ${hr.significant_lags.join(', ')} (of the first ${hr.lags_considered}) — the variance was enlarged.`
            : hr.reduction_suppressed && hr.significant_lags.length
              ? `Negative rank autocorrelation at lag(s) ${hr.significant_lags.join(', ')} would shrink the variance and make the test more significant. Estimates from short records are unreliable, so Earth Scope never reduces the variance — both columns agree.`
              : `No significant rank autocorrelation in the first ${hr.lags_considered} lags — no adjustment was needed, so both columns agree.`}{' '}
        The modified test screens the autocorrelation of the ranks, which can differ slightly from the value-based diagnostics below.
      </p>
      {hr.reliability_note && (
        <p className="mt-2 flex gap-1.5 text-xs text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {hr.reliability_note}
        </p>
      )}
      <SensitivityNote yw={yw} alpha={stats.alpha} />
    </Card>
  )
}

function SensitivityNote({ yw, alpha }: { yw: ModifiedMannKendallResult; alpha: number }) {
  return (
    <details className="mt-3 rounded-lg bg-raised px-3 py-2 text-xs text-fg-muted">
      <summary className="cursor-pointer text-fg">
        Sensitivity check: Yue &amp; Wang (2004) lag-1 correction <InfoTip label="Yue–Wang correction" text={HELP.yueWang} />
      </summary>
      <p className="mt-2">
        {yw.available
          ? `Variance factor ${yw.correction_factor.toFixed(3)}${yw.reduction_suppressed ? ` (estimated ${yw.raw_correction_factor.toFixed(2)}; reductions not applied)` : ''}, ${formatPExpr(yw.p_value)} → ${yw.significant ? 'significant' : 'not significant'} at α = ${alpha}.`
          : yw.unavailable_reason}{' '}
        Not used for the conclusions.
      </p>
    </details>
  )
}

function RateMethods({ stats, rateUnit }: { stats: StatisticsResult; rateUnit: string }) {
  const reg = stats.regression
  const sen = stats.sens_slope
  const hac = stats.advanced!.regression_hac
  const rows = [
    { m: 'OLS regression', help: HELP.ols, est: reg.slope, lo: reg.ci_lower, hi: reg.ci_upper, p: formatP(reg.p_value), ac: 'No' },
    { m: 'OLS + Newey–West (HAC)', help: HELP.hac, est: hac.slope, lo: hac.ci_lower, hi: hac.ci_upper, p: formatP(hac.p_value), ac: `Yes (${hac.max_lags} lag${hac.max_lags === 1 ? '' : 's'})` },
    { m: 'Sen’s slope', help: HELP.senCi, est: sen.slope, lo: sen.ci_lower, hi: sen.ci_upper, p: 'via MK test', ac: 'No' },
  ]
  return (
    <Card title="Rate of change: methods compared" help={HELP.senCi} className="lg:col-span-2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-sm text-fg-subtle">
              <th scope="col" className="py-2 pr-3 font-semibold">Method</th>
              <th scope="col" className="py-2 pr-3 font-semibold">Slope ({rateUnit})</th>
              <th scope="col" className="py-2 pr-3 font-semibold">95% interval</th>
              <th scope="col" className="py-2 pr-3 font-semibold">p-value</th>
              <th scope="col" className="py-2 font-semibold">Allows for autocorrelation</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const hasCi = r.lo !== null && r.hi !== null
              const includesZero = hasCi && (r.lo as number) <= 0 && (r.hi as number) >= 0
              return (
                <tr key={r.m} className="border-b border-line/50 last:border-0">
                  <th scope="row" className="py-2 pr-3 text-left font-normal text-fg">
                    {r.m}
                    <InfoTip label={r.m} text={r.help} />
                  </th>
                  <td className="stat-num py-2 pr-3">{formatSigned(r.est, 4)}</td>
                  <td className="stat-num py-2 pr-3">
                    {hasCi ? `${formatSigned(r.lo, 3)} to ${formatSigned(r.hi, 3)}` : '—'}
                    {hasCi && <span className="ml-1 text-xs text-fg-subtle">{includesZero ? '(includes 0)' : '(excludes 0)'}</span>}
                  </td>
                  <td className="stat-num py-2 pr-3">{r.p}</td>
                  <td className="py-2 text-fg-muted">{r.ac}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-fg-muted">
        Different methods answer slightly different questions, so their intervals need not match. An interval that
        excludes 0 points to a real increase or decrease under that method’s assumptions.
      </p>
    </Card>
  )
}

function Diagnostics({ stats }: { stats: StatisticsResult }) {
  const ac = stats.advanced!.autocorrelation
  const data = ac.acf.map((a) => ({ lag: a.lag, value: a.value, outside: a.outside_bound }))
  // Symmetric axis rounded up to a multiple of 0.25, with evenly spaced ticks.
  const lim = Math.ceil(Math.max(ac.bound * 1.3, ...data.map((d) => Math.abs(d.value) * 1.1), 0.25) / 0.25) * 0.25
  const step = lim > 1 ? 0.5 : 0.25
  const ticks = Array.from({ length: Math.round((2 * lim) / step) + 1 }, (_, i) => Number((-lim + i * step).toFixed(2)))
  const assess =
    ac.lag1_assessment === 'not_significant'
      ? 'within the range expected for independent years'
      : ac.lag1_assessment === 'significant_positive'
        ? 'significant positive autocorrelation'
        : 'significant negative autocorrelation'
  return (
    <Card title="Autocorrelation diagnostics" help={HELP.autocorrelation} className="lg:col-span-2">
      <div className="grid gap-4 md:grid-cols-5">
        <dl className="space-y-2 text-sm md:col-span-2">
          <div>
            <dt className="flex items-center text-fg-muted">
              Lag-1 autocorrelation (r₁) <InfoTip label="Lag-1 autocorrelation" text={HELP.lag1} />
            </dt>
            <dd className="stat-num text-lg text-fg">{ac.lag1.toFixed(3)}</dd>
            <dd className="text-xs text-fg-subtle">
              95% bound ±{ac.bound.toFixed(3)} → {assess}
            </dd>
          </div>
          <div>
            <dt className="flex items-center text-fg-muted">
              Ljung–Box test ({ac.ljung_box.lags} lags) <InfoTip label="Ljung–Box test" text={HELP.ljungBox} />
            </dt>
            <dd className="stat-num text-fg">
              Q = {ac.ljung_box.q.toFixed(2)}, {formatPExpr(ac.ljung_box.p_value)}
            </dd>
            <dd className="text-xs text-fg-subtle">
              {ac.ljung_box.significant ? 'Serial dependence detected.' : 'No serial dependence detected (low power for short records).'}
            </dd>
          </div>
          <p className="text-xs text-fg-subtle">Computed on {ac.basis}, n = {ac.n}.</p>
        </dl>
        <div className="md:col-span-3">
          <p className="mb-1 flex items-center text-xs text-fg-muted">
            Autocorrelation function <InfoTip label="Autocorrelation function" text={HELP.acf} />
          </p>
          <div className="h-48 w-full" role="img" aria-label={`Autocorrelation function for lags 1 to ${data.length}`}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 6, right: 8, bottom: 18, left: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="lag" stroke={AXIS} tick={{ fill: AXIS, fontSize: 11 }} tickLine={false}
                  label={{ value: 'Lag (years)', position: 'insideBottom', offset: -10, fill: AXIS, fontSize: 11 }} />
                <YAxis domain={[-lim, lim]} ticks={ticks} interval={0} stroke={AXIS} tick={{ fill: AXIS, fontSize: 11 }} tickLine={false} axisLine={false}
                  width={44} tickFormatter={(v: number) => v.toFixed(2)} />
                <ReferenceLine y={0} stroke={AXIS} />
                <ReferenceLine y={ac.bound} stroke={AXIS} strokeDasharray="4 4" />
                <ReferenceLine y={-ac.bound} stroke={AXIS} strokeDasharray="4 4" />
                <Tooltip
                  cursor={{ fill: 'rgba(159,177,203,0.08)' }}
                  isAnimationActive={false}
                  content={({ active, payload }) =>
                    active && payload?.length ? (
                      <div className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-xs text-fg-muted">
                        Lag {String(payload[0].payload.lag)}: r = {Number(payload[0].value).toFixed(3)}
                        <br />
                        {payload[0].payload.outside ? 'Outside the 95% bound' : 'Within the 95% bound'}
                      </div>
                    ) : null
                  }
                />
                <Bar dataKey="value" isAnimationActive={false} radius={[3, 3, 3, 3]}>
                  {data.map((d) => (
                    <Cell key={d.lag} fill={d.outside ? OUTSIDE : INSIDE} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-1 flex flex-wrap gap-x-4 text-xs text-fg-muted" aria-label="ACF legend">
            <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: INSIDE }} /> Within bound</li>
            <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-sm" style={{ background: OUTSIDE }} /> Outside bound</li>
            <li className="flex items-center gap-1.5"><span className="inline-block w-4 border-t border-dashed" style={{ borderColor: AXIS }} /> ±1.96/√n</li>
          </ul>
        </div>
      </div>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-fg-subtle">
        {ac.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </Card>
  )
}

function InterpretationCard({ stats, interpretation }: { stats: StatisticsResult; interpretation: Interpretation }) {
  const std = stats.evidence
  const rob = stats.advanced!.robust_evidence
  const same = std.category === rob.category
  return (
    <Card title="Statistical interpretation" className="lg:col-span-2">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-line-strong bg-sunken p-3">
          <p className="text-sm text-fg-subtle">Standard evidence (assumes independent years)</p>
          <p className="mt-1 font-semibold">{std.label}</p>
        </div>
        <div className={`rounded-xl border p-3 ${same ? 'border-line-strong bg-sunken' : 'border-warn/50 bg-warn/10'}`}>
          <p className="flex items-center text-sm text-fg-subtle">
            <Scale className="mr-1 size-3.5" aria-hidden /> Autocorrelation-aware evidence
            <InfoTip label="Autocorrelation-aware evidence" text={HELP.robust} />
          </p>
          <p className="mt-1 font-semibold">{rob.label}</p>
        </div>
      </div>
      <div className="mt-4 space-y-3 text-sm leading-relaxed text-fg-muted">
        {(interpretation.advanced ?? []).map((p) => (
          <p key={p}>{p}</p>
        ))}
      </div>
      <p className="mt-3 text-xs text-fg-subtle">Generated by fixed rules from the computed statistics — no AI writes or adjusts the findings.</p>
    </Card>
  )
}

export function AdvancedStatisticsPanel({
  stats,
  rateUnit,
  interpretation,
}: {
  stats: StatisticsResult
  rateUnit: string
  interpretation: Interpretation
}) {
  if (!stats.advanced) return null
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <InterpretationCard stats={stats} interpretation={interpretation} />
      <MkComparison stats={stats} />
      <RateMethods stats={stats} rateUnit={rateUnit} />
      <Diagnostics stats={stats} />
    </div>
  )
}
