import { CheckCircle2, CircleSlash } from 'lucide-react'
import type { ReactNode } from 'react'
import type { StatisticsResult } from '../../types/api'
import { formatNumber, formatP, formatSigned } from '../../utils/format'

function Row({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/70 py-2 last:border-0">
      <dt className="text-sm text-fg-muted" title={hint}>
        {label}
      </dt>
      <dd className="stat-num text-right text-sm text-fg">{value}</dd>
    </div>
  )
}

function Verdict({ significant, text }: { significant: boolean; text: string }) {
  return (
    <p
      className={`mt-4 flex items-start gap-2 rounded-lg px-3 py-2 text-sm ${
        significant ? 'bg-teal/10 text-teal' : 'bg-raised text-fg-muted'
      }`}
    >
      {significant ? <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden /> : <CircleSlash className="mt-0.5 size-4 shrink-0" aria-hidden />}
      {text}
    </p>
  )
}

export function StatisticsPanel({ stats, rateUnit }: { stats: StatisticsResult; rateUnit: string }) {
  const { regression: reg, mann_kendall: mk, sens_slope: sen, alpha } = stats
  const cl = Math.round(reg.confidence_level * 100)

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <section className="card card-pad" aria-labelledby="stat-ols">
        <h3 id="stat-ols" className="font-semibold">Linear regression (OLS)</h3>
        <p className="mt-1 text-xs text-fg-subtle">Fits Y = a + b·year to {reg.n} annual means</p>
        <dl className="mt-3">
          <Row label="Slope (b)" value={`${formatSigned(reg.slope, 4)} ${rateUnit}`} />
          <Row label={`${cl}% confidence interval`} value={`${formatSigned(reg.ci_lower, 3)} to ${formatSigned(reg.ci_upper, 3)}`} />
          <Row label="Standard error" value={formatNumber(reg.std_err, 3)} />
          <Row label="p-value" value={formatP(reg.p_value)} hint="Two-sided test of H0: slope = 0" />
          <Row label="R²" value={reg.r_squared.toFixed(3)} />
          <Row label="Degrees of freedom" value={reg.degrees_of_freedom} />
        </dl>
        <Verdict
          significant={reg.significant}
          text={
            reg.significant
              ? `Slope is significantly different from zero (p < ${alpha}).`
              : `Slope is not significantly different from zero at α = ${alpha}.`
          }
        />
      </section>

      <section className="card card-pad" aria-labelledby="stat-mk">
        <h3 id="stat-mk" className="font-semibold">Mann-Kendall trend test</h3>
        <p className="mt-1 text-xs text-fg-subtle">Tests for a monotonic trend; no linearity assumed</p>
        <dl className="mt-3">
          <Row label="Trend direction (sign of S)" value={mk.trend} />
          <Row label="S statistic" value={formatNumber(mk.s, 4)} />
          <Row label="Kendall's τ" value={mk.tau.toFixed(3)} />
          <Row label="Z statistic" value={mk.z.toFixed(3)} />
          <Row label="p-value" value={formatP(mk.p_value)} />
          <Row label="n (years)" value={mk.n} />
        </dl>
        <Verdict
          significant={mk.significant}
          text={
            mk.significant
              ? `Statistically significant ${mk.trend} monotonic trend (p < ${alpha}).`
              : `No statistically significant monotonic trend at α = ${alpha}.`
          }
        />
      </section>

      <section className="card card-pad" aria-labelledby="stat-sen">
        <h3 id="stat-sen" className="font-semibold">Sen's slope estimator</h3>
        <p className="mt-1 text-xs text-fg-subtle">Median of all {sen.n_pairs} pairwise slopes — robust to outliers</p>
        <dl className="mt-3">
          <Row label="Sen's slope" value={`${formatSigned(sen.slope, 4)} ${rateUnit}`} />
          {sen.ci_lower !== null && sen.ci_upper !== null && (
            <Row label="95% CI (Sen 1968, rank-based)" value={`${formatSigned(sen.ci_lower, 3)} to ${formatSigned(sen.ci_upper, 3)}`} />
          )}
          <Row label="Per decade" value={formatSigned(sen.slope_per_decade, 3)} />
          <Row label="Direction" value={sen.direction} />
          <Row label="OLS slope (for comparison)" value={formatSigned(reg.slope, 4)} />
        </dl>
        <p className="mt-4 rounded-lg bg-raised px-3 py-2 text-xs leading-relaxed text-fg-muted">
          Sen's slope is a rate estimate, not a test; its interval comes from ranking the pairwise slopes, not
          from the regression. Its significance is judged by the Mann-Kendall test. A large gap
          between Sen's and the OLS slope suggests a few unusual years are influencing the straight-line fit.
        </p>
      </section>
    </div>
  )
}
