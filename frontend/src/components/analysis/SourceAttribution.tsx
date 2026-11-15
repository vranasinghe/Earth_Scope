import { ChevronDown, Database, ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import type { DatasetMetadata } from '../../types/api'
import { formatDateTime } from '../../utils/format'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-fg-muted">{children}</dd>
    </div>
  )
}

export function SourceAttribution({ metadata: m }: { metadata: DatasetMetadata }) {
  return (
    <details className="group rounded-xl border border-line">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <Database className="size-4 shrink-0 text-fg-subtle" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-fg">Data source &amp; provenance</span>
          <span className="block truncate text-sm text-fg-subtle">
            NASA POWER · {m.parameter} · {m.sources.join(', ') || '—'} · retrieved {formatDateTime(m.retrieved_at)}
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-line px-5 pb-5 pt-4">
      <p className="text-sm text-fg-muted">{m.source_note}</p>
      <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Provider">{m.provider}</Field>
        <Field label="Dataset">{m.dataset_title ?? '—'}{m.api_version ? ` (API ${m.api_version})` : ''}</Field>
        <Field label="Parameter">
          <span className="font-mono">{m.parameter}</span> — {m.long_name ?? m.variable_name}
        </Field>
        <Field label="Model / source">{m.sources.length ? m.sources.join(', ') : '—'}</Field>
        <Field label="Community">{m.community}</Field>
        <Field label="Units (as reported)">{m.units_raw ?? 'not reported'}</Field>
        <Field label="Requested point">
          <span className="font-mono">
            {m.latitude_requested}, {m.longitude_requested}
          </span>
          {m.latitude_returned !== null && m.longitude_returned !== null && (
            <span className="block text-xs">
              Echoed by NASA: {m.latitude_returned}, {m.longitude_returned}
              {m.elevation_m !== null ? ` · grid-cell elevation ${m.elevation_m} m` : ''}
            </span>
          )}
        </Field>
        <Field label="Data grid cell">
          {m.grid_cell ? (
            <>
              <span className="font-mono">
                {m.grid_cell.lat_min}° to {m.grid_cell.lat_max}° lat, {m.grid_cell.lon_min}° to {m.grid_cell.lon_max}° lon
              </span>
              <span className="block text-xs">
                Values are identical anywhere inside this {m.grid_cell.lat_step}° × {m.grid_cell.lon_step}° cell
                (centre {m.grid_cell.center_latitude}, {m.grid_cell.center_longitude}).
              </span>
            </>
          ) : (
            'Not applicable'
          )}
        </Field>
        <Field label="Spatial resolution">{m.spatial_resolution}</Field>
        <Field label="Temporal resolution">
          Monthly{m.time_standard ? ` (${m.time_standard})` : ''} · {m.start_year}–{m.end_year}
          {m.latest_complete_year ? ` · latest complete year ${m.latest_complete_year}` : ''}
        </Field>
        <Field label="Retrieved">
          {formatDateTime(m.retrieved_at)}
          {m.served_from_cache && <span className="block text-xs">Served from the backend cache</span>}
        </Field>
        <Field label="Missing-value code">{m.fill_value ?? '—'} (treated as missing)</Field>
        <Field label="Documentation">
          <a className="inline-flex items-center gap-1 text-accent hover:underline" href={m.documentation_url} target="_blank" rel="noreferrer">
            Monthly API docs <ExternalLink className="size-3" aria-hidden />
          </a>
          <br />
          <a className="inline-flex items-center gap-1 text-accent hover:underline" href={m.parameter_docs_url} target="_blank" rel="noreferrer">
            Parameter definitions <ExternalLink className="size-3" aria-hidden />
          </a>
        </Field>
      </dl>
      {m.request_url && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-fg-muted hover:text-fg">Show the exact NASA POWER request</summary>
          <a href={m.request_url} target="_blank" rel="noreferrer" className="mt-2 block break-all rounded-lg bg-sunken p-3 font-mono text-xs text-accent">
            {m.request_url}
          </a>
        </details>
      )}
      </div>
    </details>
  )
}
