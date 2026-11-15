import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { SPATIAL_HELP } from '../../constants/spatialHelp'
import type {
  SignificanceBasis,
  SlopeEstimator,
  SpatialCorrection,
  SpatialLayer,
  SpatialMethod,
  SpatialSettings,
  SpatialTrendConfig,
} from '../../types/spatial'
import { InfoTip } from '../common/InfoTip'

export interface DisplayToggles {
  showGrid: boolean
  showBoundary: boolean
  showMissing: boolean
  showNonSignificant: boolean
}

interface Props {
  variableName: string
  parameter: string
  startYear: number
  endYear: number
  config: SpatialTrendConfig
  settings: SpatialSettings
  onSettings: (s: SpatialSettings) => void
  layer: SpatialLayer
  onLayer: (l: SpatialLayer) => void
  estimator: SlopeEstimator
  onEstimator: (e: SlopeEstimator) => void
  basis: SignificanceBasis
  onBasis: (b: SignificanceBasis) => void
  toggles: DisplayToggles
  onToggles: (t: DisplayToggles) => void
  trendLayersAvailable: boolean
  busy: boolean
}

const LAYERS: { id: SpatialLayer; label: string }[] = [
  { id: 'magnitude', label: 'Trend magnitude' },
  { id: 'direction', label: 'Trend direction' },
  { id: 'significance', label: 'Statistical significance' },
  { id: 'availability', label: 'Data availability' },
]

function Field({ label, htmlFor, help, children }: { label: string; htmlFor?: string; help?: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="mb-1 flex items-center text-sm font-semibold text-fg-subtle">
        {label}
        {help && <InfoTip label={label} text={help} />}
      </label>
      {children}
    </div>
  )
}

export function SpatialTrendControls(p: Props) {
  const { config, settings } = p
  const toggle = (k: keyof DisplayToggles) => p.onToggles({ ...p.toggles, [k]: !p.toggles[k] })
  return (
    <div className="card card-pad space-y-4" aria-label="Spatial trend map controls">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="text-fg-muted">
          <span className="font-semibold text-fg">{p.variableName}</span> ({p.parameter}) · {p.startYear}–{p.endYear}
        </p>
        {p.busy && (
          <span className="inline-flex items-center gap-1.5 text-xs text-accent" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> Recalculating significance…
          </span>
        )}
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-fg-subtle">Map layer</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup">
          {LAYERS.map((l) => {
            const disabled = !p.trendLayersAvailable && l.id !== 'availability'
            return (
              <button
                key={l.id}
                type="button"
                role="radio"
                aria-checked={p.layer === l.id}
                disabled={disabled}
                onClick={() => p.onLayer(l.id)}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  p.layer === l.id ? 'border-accent bg-accent/15 text-accent' : 'border-line-strong text-fg-muted hover:text-fg'
                }`}
              >
                {l.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Statistical test" htmlFor="sp-method" help={SPATIAL_HELP.method}>
          <select
            id="sp-method"
            className="input py-1.5 font-sans"
            value={settings.method}
            onChange={(e) => p.onSettings({ ...settings, method: e.target.value as SpatialMethod })}
          >
            {config.methods.map((m) => (
              <option key={m.id} value={m.id}>
                {m.short}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Multiple-testing correction" htmlFor="sp-correction" help={SPATIAL_HELP.fdr}>
          <select
            id="sp-correction"
            className="input py-1.5 font-sans"
            value={settings.correction}
            onChange={(e) => p.onSettings({ ...settings, correction: e.target.value as SpatialCorrection })}
          >
            <option value="none">Unadjusted p-values</option>
            <option value="fdr_bh">Benjamini–Hochberg FDR</option>
            <option value="fdr_by">Benjamini–Yekutieli FDR</option>
          </select>
        </Field>
        <Field label="Significance threshold (α)" htmlFor="sp-alpha" help={SPATIAL_HELP.pValue}>
          <select
            id="sp-alpha"
            className="input py-1.5 font-sans"
            value={settings.alpha}
            onChange={(e) => p.onSettings({ ...settings, alpha: Number(e.target.value) })}
          >
            {config.alphas.map((a) => (
              <option key={a} value={a}>
                {a.toFixed(2)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Slope estimator" htmlFor="sp-estimator" help={SPATIAL_HELP.slope}>
          <select id="sp-estimator" className="input py-1.5 font-sans" value={p.estimator} onChange={(e) => p.onEstimator(e.target.value as SlopeEstimator)}>
            <option value="sen">Sen’s slope (robust)</option>
            <option value="ols">OLS regression slope</option>
          </select>
        </Field>
      </div>

      {p.layer === 'significance' && settings.correction !== 'none' && (
        <div className="flex flex-wrap items-center gap-2 text-sm" role="radiogroup" aria-label="Significance classification">
          <span className="text-sm font-semibold text-fg-subtle">Classify by</span>
          {(['adjusted', 'raw'] as const).map((b) => (
            <button
              key={b}
              type="button"
              role="radio"
              aria-checked={p.basis === b}
              onClick={() => p.onBasis(b)}
              className={`rounded-lg border px-3 py-1 ${p.basis === b ? 'border-accent bg-accent/15 text-accent' : 'border-line-strong text-fg-muted hover:text-fg'}`}
            >
              {b === 'adjusted' ? 'FDR-adjusted (q ≤ α)' : 'Raw p-values (p < α)'}
            </button>
          ))}
        </div>
      )}

      <p className="rounded-lg border border-line bg-sunken/60 p-3 text-xs text-fg-muted">
        <span className="font-semibold text-fg">Active:</span> {config.method_label} · {config.correction_label} · α = {config.alpha}
        {' · '}
        {config.n_hypotheses} cells in the correction family. Changing these options re-classifies the same cached NASA data; nothing is downloaded again.
      </p>

      <fieldset className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-fg-muted">
        <legend className="sr-only">Display options</legend>
        {(
          [
            ['showGrid', 'Grid boundaries'],
            ['showBoundary', 'Region boundary'],
            ['showMissing', 'Missing-data cells'],
            ['showNonSignificant', 'Non-significant cells (filled)'],
          ] as const
        ).map(([k, label]) => (
          <label key={k} className="inline-flex cursor-pointer items-center gap-2">
            <input type="checkbox" className="accent-[var(--color-accent)]" checked={p.toggles[k]} onChange={() => toggle(k)} />
            {label}
          </label>
        ))}
      </fieldset>
    </div>
  )
}
