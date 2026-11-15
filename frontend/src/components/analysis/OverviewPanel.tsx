import type { AnalysisResponse } from '../../types/api'
import { formatCoord } from '../../utils/format'

function Item({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm text-fg-subtle">{label}</dt>
      <dd className={`mt-0.5 break-words text-[0.9375rem] text-fg ${mono ? 'stat-num' : ''}`}>
        {value}
      </dd>
    </div>
  )
}

export function OverviewPanel({ result, locationName }: { result: AnalysisResponse; locationName?: string }) {
  const m = result.metadata
  const s = result.summary
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-4 min-[420px]:grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
      <Item label="Variable" value={`${m.variable_name} (${m.parameter})`} />
      <Item label="Location" value={locationName ? `${locationName} (grid cell)` : 'Selected grid cell'} />
      <Item label="Requested coordinates" value={formatCoord(m.latitude_requested, m.longitude_requested)} mono />
      {m.grid_cell && (
        <Item
          label="Data grid cell centre (MERRA-2)"
          value={`${formatCoord(m.grid_cell.center_latitude, m.grid_cell.center_longitude, 3)}${m.elevation_m !== null ? ` · ${m.elevation_m} m` : ''}`}
          mono
        />
      )}
      <Item label="Analysis period" value={`${m.start_year} – ${m.end_year}`} mono />
      <Item label="Monthly observations" value={`${s.n_monthly_valid} valid of ${s.n_monthly_total}`} mono />
      <Item label="Annual records used" value={`${s.n_annual_used} of ${s.n_annual_total} years`} mono />
      <Item label="Data source" value={`NASA POWER · ${m.sources.join(', ')}`} />
      <Item label="Units (NASA)" value={m.units_raw ? `${m.units_raw} → ${m.unit_display}` : `${m.unit_display} (assumed)`} />
    </dl>
  )
}
