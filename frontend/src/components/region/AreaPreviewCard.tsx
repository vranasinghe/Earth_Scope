import { AlertTriangle, CheckCircle2, ChevronDown, Loader2 } from 'lucide-react'
import type { ApiError } from '../../services/api'
import type { AreaPreviewResponse } from '../../types/area'
import { formatNumber } from '../../utils/format'
import { ErrorState } from '../common/States'

interface Props {
  data: AreaPreviewResponse | null
  loading: boolean
  error: ApiError | null
  onRetry: () => void
  emptyText: string
}

/** Area preflight shown before any NASA request: the four numbers that decide the run first, provenance on demand. */
export function AreaPreviewCard({ data, loading, error, onRetry, emptyText }: Props) {
  if (error) return <ErrorState error={error} title="This area cannot be analysed" onRetry={error.retryable ? onRetry : undefined} />
  if (!data && loading)
    return (
      <p className="flex items-center gap-2 text-sm text-fg-muted" role="status">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Checking the area and estimating the NASA requests…
      </p>
    )
  if (!data) return <p className="text-sm text-fg-subtle">{emptyText}</p>
  const a = data.area
  const p = data.preflight
  const b = a.bbox
  const primary: [string, string][] = [
    ['NASA grid cells', `${p.n_cells.toLocaleString()} (0.5° × 0.625°)`],
    ['NASA requests (tiles)', String(p.n_tiles)],
    ['Area', `${formatNumber(Math.round(a.area_km2), 7)} km²`],
    ['Estimated time', `~${Math.max(1, Math.round(p.estimated_seconds))} s + ~${Math.max(1, Math.round(p.estimated_spatial_seconds))} s map`],
  ]
  const details: [string, string][] = [
    [a.kind === 'country' ? 'Country' : 'Polygon', a.iso3 ? `${a.name} (${a.iso3})` : a.name],
    ['Geodesic area (WGS84)', `${formatNumber(Math.round(a.geodesic_area_km2), 7)} km²`],
    ['Parts · vertices', `${a.n_components} · ${a.n_vertices.toLocaleString()}`],
    ['Bounding box', `${b.lat_min.toFixed(2)}…${b.lat_max.toFixed(2)}° lat, ${b.lon_min.toFixed(2)}…${b.lon_max.toFixed(2)}° lon`],
    ['Data values', `${p.n_values.toLocaleString()} (${p.n_months} months)`],
  ]
  if (a.boundary) details.push(['Boundary source', `${a.boundary.source} · ${a.boundary.version}`], ['Licence', a.boundary.license ?? '—'])
  return (
    <div aria-live="polite">
      <p className="flex items-center gap-2 font-semibold">
        {p.available ? (
          <>
            <CheckCircle2 className="size-4 text-ok" aria-hidden /> Ready to analyse
          </>
        ) : (
          <>
            <AlertTriangle className="size-4 text-warn" aria-hidden /> Exceeds the instant-analysis limits
          </>
        )}
        <span className="font-normal text-fg-muted">· {a.iso3 ? `${a.name} (${a.iso3})` : a.name}</span>
        {loading && <Loader2 className="ml-auto size-4 animate-spin text-fg-subtle" aria-label="Updating" />}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        {primary.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-sm text-fg-subtle">{k}</dt>
            <dd className="stat-num break-words text-[0.9375rem] text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      {!p.available && (
        <div className="mt-4 rounded-lg bg-warn/10 p-3.5 text-sm" role="alert">
          <p className="font-semibold text-fg">
            This region exceeds the instant (synchronous) analysis limit. Use the background analysis below — it runs on a server worker within its
            own, larger budget.
          </p>
          <ul className="mt-1.5 list-disc pl-5 text-fg-muted">
            {[...p.reasons, ...p.suggestions].map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
          <p className="mt-1.5 text-xs text-fg-subtle">Earth Scope never downsamples or analyses only part of an area while calling it complete.</p>
        </div>
      )}
      {p.small_area_warning && <p className="mt-3 text-sm text-warn">{p.small_area_warning}</p>}
      <details className="disclosure mt-4">
        <summary>
          <ChevronDown className="size-4 transition-transform [details[open]_&]:rotate-180" aria-hidden /> Boundary and geometry
        </summary>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-3 min-[420px]:grid-cols-2 xl:grid-cols-3">
          {details.map(([k, v]) => (
            <div key={k} className="min-w-0">
              <dt className="text-sm text-fg-subtle">{k}</dt>
              <dd className="break-words text-[0.9375rem] text-fg">{v}</dd>
            </div>
          ))}
        </dl>
        {a.notes.map((n) => (
          <p key={n} className="mt-2 text-sm text-fg-subtle">
            {n}
          </p>
        ))}
        <p className="mt-3 text-sm text-fg-subtle">
          {a.kind === 'country'
            ? 'Results describe the area inside this boundary dataset’s representation of the country; another dataset, or another treatment of disputed or overseas territories, can give slightly different results.'
            : 'Results describe the area inside your polygon. Cells cut by its edge count only for their part inside.'}
        </p>
      </details>
    </div>
  )
}
