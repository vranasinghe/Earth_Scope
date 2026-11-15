import type { SignificanceBasis, SlopeEstimator, SpatialCorrection, SpatialLayer } from '../../types/spatial'
import { formatSigned } from '../../utils/format'
import {
  AVAILABILITY_COLORS,
  AVAILABILITY_LABELS,
  DIRECTION_COLORS,
  DIRECTION_LABELS,
  DIVERGING_GRADIENT,
  SIGNIFICANCE_COLORS,
  SIGNIFICANCE_LABELS,
} from '../../utils/spatialColors'

interface Props {
  layer: SpatialLayer
  maxAbs: number
  rateUnit: string
  variableName: string
  estimator: SlopeEstimator
  basis: SignificanceBasis
  correction: SpatialCorrection
  alpha: number
  showNonSignificant: boolean
  showMissing: boolean
}

function Swatch({ color, label, dashed, outline }: { color: string; label: string; dashed?: boolean; outline?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-block size-3.5 rounded-sm"
        style={{ background: color, border: outline ? `2px solid ${outline}` : dashed ? '1px dashed #94a3b8' : '1px solid #0a1322' }}
        aria-hidden
      />
      {label}
    </span>
  )
}

export function SpatialTrendLegend(p: Props) {
  const est = p.estimator === 'sen' ? 'Sen’s slope' : 'OLS slope'
  const basisText =
    p.correction === 'none' || p.basis === 'raw' ? `raw p < ${p.alpha}` : `${p.correction === 'fdr_bh' ? 'Benjamini–Hochberg' : 'Benjamini–Yekutieli'} q ≤ ${p.alpha}`
  return (
    <div className="mt-3 space-y-2 text-xs text-fg-muted" aria-label="Map legend">
      {p.layer === 'magnitude' && (
        <>
          <p className="font-semibold text-fg">
            {p.variableName} trend ({p.rateUnit}) — {est}
          </p>
          <div className="flex max-w-md items-center gap-2">
            <span className="stat-num">{formatSigned(-p.maxAbs)}</span>
            <span className="h-3 flex-1 rounded" style={{ background: DIVERGING_GRADIENT }} aria-hidden />
            <span className="stat-num">{formatSigned(p.maxAbs)}</span>
          </div>
          <p>
            Blue = decrease, red = increase, pale = close to zero. The scale is symmetric around zero and fixed for this analysis. Colour shows the slope only, not
            significance; cells with a <span className="font-semibold text-fg">dark outline</span> are significant ({basisText}).
          </p>
        </>
      )}
      {p.layer === 'direction' && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {(['increasing', 'decreasing', 'near_zero'] as const).map((d) => (
            <Swatch key={d} color={DIRECTION_COLORS[d]} label={DIRECTION_LABELS[d]} />
          ))}
          <Swatch color="#0b1220" label={`Dark outline = significant (${basisText})`} outline="#0b1220" />
          <span>Direction is the sign of the {est}; it is not a significance result.</span>
        </div>
      )}
      {p.layer === 'significance' && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {(['significant_increasing', 'significant_decreasing', 'not_significant', 'not_testable', 'insufficient_data', 'excluded'] as const).map((s) => (
            <Swatch key={s} color={SIGNIFICANCE_COLORS[s]} label={SIGNIFICANCE_LABELS[s]} dashed={s === 'insufficient_data' || s === 'excluded'} />
          ))}
          <span className="basis-full">
            Classified by {basisText}. “Not statistically significant” means the evidence is insufficient under this test — not that the trend is exactly zero.
          </span>
        </div>
      )}
      {p.layer === 'availability' && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5">
          {(Object.keys(AVAILABILITY_COLORS) as (keyof typeof AVAILABILITY_COLORS)[]).map((k) => (
            <Swatch key={k} color={AVAILABILITY_COLORS[k]} label={AVAILABILITY_LABELS[k]} dashed={k === 'excluded'} />
          ))}
        </div>
      )}
      {p.layer !== 'availability' && (
        <p>
          <span className="inline-block size-3 border border-dashed border-warn align-middle" /> Amber dashed outline: no trend test (insufficient data, no variation or failed).
          {!p.showNonSignificant && ' Non-significant cells are drawn as outlines only; they are still in the correction family and the summary.'}
          {!p.showMissing && ' Cells without a trend test are hidden from the drawing but still counted in the summary.'}
        </p>
      )}
    </div>
  )
}
