// Regional downloads, built only from the data returned by the backend.

import type { RegionalAnalysisResponse, RegionalMetadata } from '../types/api'

export function cell(v: unknown): string {
  if (v === null || v === undefined) return ''
  const s = String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function save(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Country / polygon provenance lines (empty for rectangles). */
export function areaHeaderLines(m: RegionalMetadata): string[] {
  if (!m.area_mode || m.area_mode === 'rectangle') return []
  const lines = [
    `# Analysis mode: ${m.area_mode === 'country' ? 'COUNTRY BOUNDARY' : 'CUSTOM POLYGON'} — ${m.area_name}${m.iso3 ? ` (ISO ${m.iso3})` : ''}`,
    `# Geometry: ${m.geometry_id}; ${m.n_components} part(s), ${m.n_vertices} vertices; WGS84 lon/lat; area ${Math.round(m.polygon_area_km2 ?? m.region_area_km2)} km2 (equal-area), ${Math.round(m.geodesic_area_km2 ?? 0)} km2 (WGS84 geodesic)`,
  ]
  if (m.boundary)
    lines.push(
      `# Boundary: ${m.boundary.dataset}; ${m.boundary.version}; id ${m.boundary.boundary_id}; licence ${m.boundary.license ?? 'n/a'}`,
      `# Attribution: ${m.boundary.attribution}`,
      '# Note: another boundary dataset (or treatment of disputed / overseas territories) can give slightly different results.',
    )
  return lines
}

/** Every NASA request behind the result (one URL for rectangles, all tile URLs for countries / polygons). */
export function requestLines(m: RegionalMetadata): string[] {
  if (m.request_manifest?.length)
    return [
      `# NASA requests: ${m.request_manifest.length} regional tile(s)`,
      ...m.request_manifest.map((t) => `#   ${t.tile}: ${t.url ?? 'n/a'}`),
    ]
  return m.request_url ? [`# NASA request: ${m.request_url}`] : []
}

function header(r: RegionalAnalysisResponse, title: string): string[] {
  const m = r.metadata
  const b = m.bbox
  const isArea = m.area_mode === 'country' || m.area_mode === 'polygon'
  return [
    `# Earth Scope — ${isArea ? (m.area_mode === 'country' ? 'country' : 'polygon') : 'regional'} ${title}`,
    `# DATA MODE: ${m.data_mode}`,
    `# Provider: ${m.provider}`,
    `# Parameter: ${m.parameter} (${m.long_name ?? m.variable_name}); community ${m.community}; units (as reported): ${m.units_raw ?? 'n/a'}`,
    `# Sources: ${m.sources.join(', ') || 'n/a'}`,
    ...areaHeaderLines(m),
    isArea
      ? `# Bounding box of the area: lat ${b.lat_min} to ${b.lat_max}, lon ${b.lon_min} to ${b.lon_max}`
      : `# Region (bounding box): lat ${b.lat_min} to ${b.lat_max}, lon ${b.lon_min} to ${b.lon_max}; area ${Math.round(m.region_area_km2)} km2 — a rectangle, not a country or administrative boundary`,
    `# Grid: ${m.grid_resolution}; cells used ${m.n_cells_used}, excluded ${m.n_cells_excluded}`,
    `# Aggregation: ${m.aggregation_method}`,
    `# Partial cells: ${m.partial_cell_rule}`,
    `# Coverage threshold per month: ${Math.round(m.coverage_threshold * 100)}% of the analysed area; mean coverage ${(r.summary.mean_coverage * 100).toFixed(1)}%`,
    `# Period: ${m.start_year}-${m.end_year}; temporal resolution: monthly`,
    `# Retrieved: ${m.retrieved_at}`,
    ...requestLines(m),
    '# Missing values are left empty (never zero-filled or interpolated).',
  ]
}

function base(r: RegionalAnalysisResponse): string {
  const m = r.metadata
  const b = m.bbox
  if (m.area_mode === 'country') return `earthscope_country_${m.iso3}_${m.parameter}_${m.start_year}-${m.end_year}`
  if (m.area_mode === 'polygon')
    return `earthscope_polygon_${(m.area_name ?? 'area').replace(/[^\w-]+/g, '_').slice(0, 40)}_${m.parameter}_${m.start_year}-${m.end_year}`
  return `earthscope_region_${m.parameter}_${b.lat_min}_${b.lat_max}_${b.lon_min}_${b.lon_max}_${m.start_year}-${m.end_year}`
}

export function downloadRegionalMonthly(r: RegionalAnalysisResponse) {
  const u = r.metadata.units_raw ?? ''
  const rows = [
    ...header(r, 'monthly series'),
    'date,year,month,regional_mean,unit,status,coverage,valid_cells,missing_cells,valid_area_km2,spatial_sd,min_cell_value,max_cell_value',
    ...r.monthly.map((m) =>
      [m.date, m.year, m.month, m.value, u, m.status, m.coverage.toFixed(4), m.valid_cells, m.missing_cells, m.valid_area_km2.toFixed(1), m.spatial_sd, m.min_value, m.max_value]
        .map(cell)
        .join(','),
    ),
  ]
  save(`${base(r)}_monthly.csv`, rows.join('\n') + '\n', 'text/csv;charset=utf-8')
}

export function downloadRegionalAnnual(r: RegionalAnalysisResponse) {
  const u = r.metadata.units_raw ?? ''
  const rows = [
    ...header(r, 'annual series (day-weighted)'),
    'year,regional_annual_mean,unit,valid_months,status,used_in_trend,spatial_sd_across_cells',
    ...r.annual.map((a) => [a.year, a.value, u, a.valid_months, a.status, a.used_in_trend, a.spatial_sd].map(cell).join(',')),
  ]
  save(`${base(r)}_annual.csv`, rows.join('\n') + '\n', 'text/csv;charset=utf-8')
}

export function downloadRegionalCells(r: RegionalAnalysisResponse) {
  const rows = [
    ...header(r, 'grid-cell metadata'),
    'centre_lat,centre_lon,lat_min,lat_max,lon_min,lon_max,cell_area_km2,overlap_area_km2,overlap_fraction,weight,status,exclusion_reason,valid_months,total_months,period_mean',
    ...r.cells.map((c) =>
      [c.latitude, c.longitude, c.lat_min, c.lat_max, c.lon_min, c.lon_max, c.cell_area_km2.toFixed(2), c.overlap_area_km2.toFixed(2),
        c.overlap_fraction.toFixed(4), c.weight.toFixed(6), c.status, c.exclusion_reason, c.valid_months, c.total_months, c.period_mean]
        .map(cell)
        .join(','),
    ),
  ]
  save(`${base(r)}_grid_cells.csv`, rows.join('\n') + '\n', 'text/csv;charset=utf-8')
}

export function downloadRegionalStatistics(r: RegionalAnalysisResponse) {
  const body = {
    generated_by: 'Earth Scope — regional analysis',
    exported_at: new Date().toISOString(),
    data_mode: r.metadata.data_mode,
    analysis_mode: r.metadata.area_mode ?? 'rectangle',
    area: r.metadata.area_mode && r.metadata.area_mode !== 'rectangle'
      ? { name: r.metadata.area_name, iso3: r.metadata.iso3, geometry_id: r.metadata.geometry_id, boundary: r.metadata.boundary, area_km2: r.metadata.polygon_area_km2 }
      : null,
    region: r.metadata.bbox,
    request_urls: r.metadata.request_manifest ? r.metadata.request_manifest.map((t) => t.url) : [r.metadata.request_url],
    completeness: { coverage_threshold: r.metadata.coverage_threshold, min_valid_months_per_year: r.summary.min_valid_months_per_year, mean_coverage: r.summary.mean_coverage },
    variable: { id: r.metadata.variable_id, parameter: r.metadata.parameter, unit: r.metadata.unit_display, rate_unit: r.metadata.rate_unit },
    aggregation_method: r.metadata.aggregation_method,
    statistics: r.statistics,
    analysis_message: r.analysis_message,
    analysis_error: r.analysis_error,
    interpretation: r.interpretation,
  }
  save(`${base(r)}_statistics.json`, JSON.stringify(body, null, 2), 'application/json')
}

export function downloadRegionalMetadata(r: RegionalAnalysisResponse) {
  const body = {
    generated_by: 'Earth Scope — regional analysis',
    exported_at: new Date().toISOString(),
    metadata: r.metadata,
    summary: r.summary,
    warnings: r.warnings,
    cell_years: r.cell_years,
    cells: r.cells,
    statistics: r.statistics,
    interpretation: r.interpretation,
  }
  save(`${base(r)}_full_metadata.json`, JSON.stringify(body, null, 2), 'application/json')
}
