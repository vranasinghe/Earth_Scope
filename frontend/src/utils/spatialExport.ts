// Spatial trend downloads, built only from the backend response.

import type { SpatialCellDetail, SpatialTrendCell, SpatialTrendResponse } from '../types/spatial'
import { areaHeaderLines, cell as csv, requestLines, save } from './regionalExport'

function provenance(r: Pick<SpatialTrendResponse, 'metadata' | 'config'>) {
  const m = r.metadata
  const c = r.config
  return {
    data_mode: m.data_mode,
    provider: m.provider,
    parameter: m.parameter,
    community: m.community,
    sources: m.sources,
    temporal_resolution: m.temporal_resolution,
    grid_resolution: m.grid_resolution,
    bbox: m.bbox,
    analysis_mode: m.area_mode ?? 'rectangle',
    area_name: m.area_name ?? null,
    iso3: m.iso3 ?? null,
    geometry_id: m.geometry_id ?? null,
    boundary: m.boundary ?? null,
    request_url: m.request_url,
    request_urls: m.request_manifest ? m.request_manifest.map((t) => t.url) : m.request_url ? [m.request_url] : [],
    retrieved_at: m.retrieved_at,
    statistical_method: c.method,
    statistical_method_label: c.method_label,
    correction: c.correction,
    correction_label: c.correction_label,
    alpha: c.alpha,
    n_hypotheses: c.n_hypotheses,
  }
}

function headerLines(r: Pick<SpatialTrendResponse, 'metadata' | 'config'>, title: string): string[] {
  const m = r.metadata
  const c = r.config
  const b = m.bbox
  return [
    `# Earth Scope — ${title}`,
    `# DATA MODE: ${m.data_mode}`,
    `# Provider: ${m.provider}`,
    `# Parameter: ${m.parameter} (${m.long_name ?? m.variable_name}); community ${m.community}; sources ${m.sources.join(', ') || 'n/a'}`,
    ...areaHeaderLines(m),
    `# Bounding box: lat ${b.lat_min} to ${b.lat_max}, lon ${b.lon_min} to ${b.lon_max}${m.area_mode && m.area_mode !== 'rectangle' ? '' : ' — a rectangle, not an administrative boundary'}`,
    `# Grid: ${m.grid_resolution}. Each value is a gridded model/satellite-derived estimate, not a station measurement.`,
    `# Period: ${m.start_year}-${m.end_year}; annual = day-weighted mean of >= ${c.min_valid_months_per_year} valid months; >= ${c.min_years} usable years per cell`,
    `# Test: ${c.method_label}; correction: ${c.correction_label}; alpha ${c.alpha}; hypotheses in family ${c.n_hypotheses}`,
    `# Rules: ${c.raw_rule}; ${c.adjusted_rule}`,
    ...requestLines(m),
    '# Empty fields = not available (never zero-filled).',
  ]
}

function fileBase(r: Pick<SpatialTrendResponse, 'metadata'>): string {
  const m = r.metadata
  const b = m.bbox
  if (m.area_mode === 'country') return `earthscope_spatial_country_${m.iso3}_${m.parameter}_${m.start_year}-${m.end_year}`
  if (m.area_mode === 'polygon')
    return `earthscope_spatial_polygon_${(m.area_name ?? 'area').replace(/[^\w-]+/g, '_').slice(0, 40)}_${m.parameter}_${m.start_year}-${m.end_year}`
  return `earthscope_spatial_${m.parameter}_${b.lat_min}_${b.lat_max}_${b.lon_min}_${b.lon_max}_${m.start_year}-${m.end_year}`
}

export const SPATIAL_CSV_COLUMNS = [
  'cell_id', 'latitude', 'longitude', 'variable', 'unit', 'slope', 'trend_direction', 'sen_slope', 'sen_ci_lower', 'sen_ci_upper',
  'raw_p_value', 'adjusted_p_value', 'statistical_method', 'fdr_method', 'significance_status', 'valid_years', 'overlap_area',
  'data_status',
  // extra context
  'lat_min', 'lat_max', 'lon_min', 'lon_max', 'overlap_fraction', 'weight', 'ols_p_value', 'ols_r_squared', 'mk_p_value',
  'hr_canonical_p_value', 'hr_conservative_p_value', 'yw_canonical_p_value', 'lag1_autocorrelation', 'raw_significance_status',
  'valid_months', 'data_mode',
] as const

export function spatialCsvRow(c: SpatialTrendCell, r: SpatialTrendResponse): unknown[] {
  const m = r.metadata
  return [
    c.id, c.latitude, c.longitude, m.parameter, m.units_raw ?? m.unit_display, c.ols_slope, c.direction_sen, c.sen_slope,
    c.sen_ci_lower, c.sen_ci_upper, c.raw_p_value, c.adjusted_p_value, r.config.method, r.config.correction, c.status,
    c.valid_years, c.overlap_area_km2.toFixed(2), c.data_status,
    c.lat_min, c.lat_max, c.lon_min, c.lon_max, c.overlap_fraction.toFixed(4), c.weight.toFixed(6), c.ols_p_value,
    c.ols_r_squared, c.mk_p_value, c.hr_canonical_p_value, c.hr_conservative_p_value, c.yw_canonical_p_value,
    c.lag1_autocorrelation, c.raw_status, c.valid_months, m.data_mode,
  ]
}

export function spatialCsv(r: SpatialTrendResponse): string {
  const lines = [
    ...headerLines(r, 'per-grid-cell spatial trends'),
    '# slope = OLS slope per year; trend_direction from Sen’s slope (near_zero = display rule); overlap_area in km2',
    SPATIAL_CSV_COLUMNS.join(','),
    ...r.cells.map((c) => spatialCsvRow(c, r).map(csv).join(',')),
  ]
  return lines.join('\n')
}

export function spatialGeoJson(r: SpatialTrendResponse) {
  return {
    type: 'FeatureCollection',
    // Foreign member (RFC 7946 §6.1) carrying provenance for the whole file.
    metadata: { generated_by: 'Earth Scope', exported_at: new Date().toISOString(), ...provenance(r) },
    features: r.cells.map((c) => ({
      type: 'Feature',
      id: c.id,
      // Polygon mode: the part of the cell inside the area; otherwise the full cell.
      // Exterior rings are counter-clockwise and closed (RFC 7946 §3.1.6).
      geometry: c.clip ?? {
        type: 'Polygon',
        coordinates: [[
          [c.lon_min, c.lat_min], [c.lon_max, c.lat_min], [c.lon_max, c.lat_max], [c.lon_min, c.lat_max], [c.lon_min, c.lat_min],
        ]],
      },
      properties: {
        cell_id: c.id, ...c, clip: undefined,
        geometry_is_clipped: !!c.clip,
        full_cell_bounds: [c.lon_min, c.lat_min, c.lon_max, c.lat_max],
        statistical_method: r.config.method, fdr_method: r.config.correction, alpha: r.config.alpha,
        data_mode: r.metadata.data_mode, provider: r.metadata.provider, parameter: r.metadata.parameter,
      },
    })),
  }
}

export function spatialSummaryJson(r: SpatialTrendResponse) {
  return {
    generated_by: 'Earth Scope',
    exported_at: new Date().toISOString(),
    provenance: provenance(r),
    configuration: r.config,
    spatial_summary: r.summary,
    regional_aggregate: r.regional_aggregate,
    interpretation: r.interpretation,
    warnings: r.warnings,
    nasa_metadata: r.metadata,
  }
}

export function cellSeriesCsv(d: SpatialCellDetail): string {
  const c = d.cell
  const regional = new Map((d.regional_annual ?? []).map((a) => [a.year, a.value]))
  const trend = (y: number) => (c.ols_slope !== null && c.ols_intercept !== null ? c.ols_intercept + c.ols_slope * y : null)
  return [
    ...headerLines(d, `annual series of grid cell ${c.id}`),
    `# Cell centre ${c.latitude}, ${c.longitude}; bounds lat ${c.lat_min}..${c.lat_max}, lon ${c.lon_min}..${c.lon_max}; ${(c.overlap_fraction * 100).toFixed(0)}% inside the region`,
    'year,cell_annual_mean,valid_months,used_in_trend,ols_trend_value,regional_aggregate_annual_mean',
    ...d.annual.map((a) => [a.year, a.value, a.valid_months, a.used_in_trend, a.used_in_trend ? trend(a.year) : null, regional.get(a.year) ?? null].map(csv).join(',')),
  ].join('\n')
}

export const downloadSpatialCsv = (r: SpatialTrendResponse) => save(`${fileBase(r)}_cells.csv`, spatialCsv(r), 'text/csv;charset=utf-8')
export const downloadSpatialGeoJson = (r: SpatialTrendResponse) =>
  save(`${fileBase(r)}.geojson`, JSON.stringify(spatialGeoJson(r), null, 1), 'application/geo+json')
export const downloadSpatialSummary = (r: SpatialTrendResponse) =>
  save(`${fileBase(r)}_summary.json`, JSON.stringify(spatialSummaryJson(r), null, 2), 'application/json')
export const downloadCellSeries = (d: SpatialCellDetail) =>
  save(`${fileBase(d)}_cell_${d.cell.id}.csv`, cellSeriesCsv(d), 'text/csv;charset=utf-8')
