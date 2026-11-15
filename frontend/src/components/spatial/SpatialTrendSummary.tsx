import type { ReactNode } from 'react'
import type { RegionalAggregate, SpatialSummary, SpatialTrendConfig } from '../../types/spatial'
import { formatP, formatSigned } from '../../utils/format'

const pct = (v: number | null) => (v === null ? '—' : `${v.toFixed(v > 0 && v < 1 ? 1 : 0)}%`)

function Cell({ label, count, detail, tone, dot }: { label: string; count: number; detail: ReactNode; tone?: string; dot?: string }) {
  return (
    <div className="flex min-w-0 flex-col bg-surface px-4 py-4">
      <div className="flex items-center gap-1.5 text-sm text-fg-muted">
        {dot && <span className="size-2 shrink-0 rounded-full" style={{ background: dot }} aria-hidden />}
        {label}
      </div>
      <p className={`stat-num mt-1 text-2xl font-semibold ${tone ?? 'text-fg'}`}>{count}</p>
      <div className="mt-0.5 text-xs text-fg-subtle">{detail}</div>
    </div>
  )
}

export function SpatialTrendSummary({
  summary: s,
  config,
  regional,
  rateUnit,
}: {
  summary: SpatialSummary
  config: SpatialTrendConfig
  regional: RegionalAggregate | null
  rateUnit: string
}) {
  const c = s.categories
  const tested = (k: 'significant_increasing' | 'significant_decreasing' | 'not_significant') => (
    <>
      {pct(c[k].pct_of_tested_cells)} of tested cells · {pct(c[k].pct_of_tested_area)} of tested area
    </>
  )
  return (
    <div className="space-y-4">
      <div className="card overflow-hidden">
        <div className="grid gap-px bg-line min-[420px]:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
          <Cell label="Grid cells" count={s.n_cells_total} detail={<>{s.n_cells_included} included{s.n_cells_excluded ? ` · ${s.n_cells_excluded} water/ice` : ''}</>} />
          <Cell label="Valid trend tests" count={s.n_hypotheses}
            detail={<>{pct(s.n_cells_included ? (s.n_hypotheses / s.n_cells_included) * 100 : null)} of cells · {pct(s.included_area_km2 ? (s.tested_area_km2 / s.included_area_km2) * 100 : null)} of area</>} />
          <Cell label="Significant increase" count={c.significant_increasing.count} tone="text-[var(--color-trend-up)]" dot="var(--color-trend-up)" detail={tested('significant_increasing')} />
          <Cell label="Significant decrease" count={c.significant_decreasing.count} tone="text-[var(--color-trend-down)]" dot="var(--color-trend-down)" detail={tested('significant_decreasing')} />
          <Cell label="Not significant" count={c.not_significant.count} detail={tested('not_significant')} />
          <Cell label="Not testable" count={c.insufficient_data.count + c.not_testable.count}
            detail={<>{pct((c.insufficient_data.pct_of_included_cells ?? 0) + (c.not_testable.pct_of_included_cells ?? 0))} of cells · {pct((c.insufficient_data.pct_of_included_area ?? 0) + (c.not_testable.pct_of_included_area ?? 0))} of area</>} />
        </div>
      </div>
      <p className="text-sm text-fg-subtle">
        Cell percentages count grid cells; area percentages use each cell’s true area inside the selection. They differ because edge cells are only partly inside and cells shrink towards the poles.
      </p>

      <div className="grid gap-4 lg:grid-cols-2">
        <dl className="panel grid grid-cols-2 gap-x-4 gap-y-3 p-5 text-sm">
          <div className="col-span-2 font-bold text-fg">Multiple-testing summary</div>
          <div><dt className="text-sm text-fg-subtle">Test</dt><dd className="text-fg">{config.method_label}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Correction</dt><dd className="text-fg">{config.correction_label}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Hypotheses in family</dt><dd className="stat-num text-fg">{s.n_hypotheses}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Threshold</dt><dd className="stat-num text-fg">α = {config.alpha}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Raw p &lt; α</dt><dd className="stat-num text-fg">{s.n_raw_significant} cells</dd></div>
          <div>
            <dt className="text-sm text-fg-subtle">FDR discoveries</dt>
            <dd className="stat-num text-fg">{s.n_fdr_discoveries === null ? 'no correction applied' : `${s.n_fdr_discoveries} cells`}</dd>
          </div>
          <div className="col-span-2"><dt className="text-sm text-fg-subtle">Spatial coverage of tests</dt><dd className="text-fg">{pct(s.included_area_km2 ? (s.tested_area_km2 / s.included_area_km2) * 100 : null)} of the included area has a valid trend test</dd></div>
        </dl>

        <dl className="panel grid grid-cols-2 gap-x-4 gap-y-3 p-5 text-sm">
          <div className="col-span-2 font-bold text-fg">Local cells vs the regional aggregate</div>
          <div><dt className="text-sm text-fg-subtle">Cells with positive / negative slope</dt><dd className="stat-num text-fg">{s.n_positive_slope} / {s.n_negative_slope}{s.n_near_zero_slope ? ` (+${s.n_near_zero_slope} near zero)` : ''}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Regional aggregate OLS slope</dt><dd className="stat-num text-fg">{regional?.ols_slope != null ? `${formatSigned(regional.ols_slope)} ${rateUnit}` : '—'}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Area-weighted mean of cell OLS slopes</dt><dd className="stat-num text-fg">{s.area_weighted_mean_ols_slope !== null ? `${formatSigned(s.area_weighted_mean_ols_slope)} ${rateUnit}` : '—'}</dd></div>
          <div><dt className="text-sm text-fg-subtle">Regional Mann-Kendall p</dt><dd className="stat-num text-fg">{regional?.mk_p_value != null ? formatP(regional.mk_p_value) : '—'}</dd></div>
          <p className="col-span-2 text-xs text-fg-muted">
            {s.slope_identity_exact
              ? 'Every included cell is complete in every month, so the regional OLS slope equals the area-weighted mean of cell OLS slopes exactly (OLS is linear in the data). Sen’s slopes and p-values do not combine this way.'
              : 'Some cells have missing months or no trend test, so the regional slope and the average of cell slopes are different quantities and need not match.'}
          </p>
        </dl>
      </div>
    </div>
  )
}
