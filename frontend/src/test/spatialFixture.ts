// Small hand-made SpatialTrendResponse for unit tests (not NASA data).
import type { RegionalMetadata } from '../types/api'
import type { SpatialTrendCell, SpatialTrendResponse } from '../types/spatial'

export function makeCell(over: Partial<SpatialTrendCell> = {}): SpatialTrendCell {
  return {
    id: '7.000_80.6250', latitude: 7, longitude: 80.625, lat_min: 6.75, lat_max: 7.25, lon_min: 80.3125, lon_max: 80.9375,
    cell_area_km2: 3800, overlap_area_km2: 3800, overlap_fraction: 1, weight: 0.25, valid_months: 240, total_months: 240,
    valid_years: 20, total_years: 20, period_mean: 27.1, data_status: 'analysed', availability: 'complete', reason: null,
    first_year: 2001, last_year: 2020, ols_slope: 0.03, ols_intercept: -33, ols_p_value: 0.001, ols_r_squared: 0.6,
    ols_std_err: 0.005, ols_ci_lower: 0.02, ols_ci_upper: 0.04, hac_p_value: 0.002, sen_slope: 0.028, sen_ci_lower: 0.018,
    sen_ci_upper: 0.04, mk_s: 120, mk_tau: 0.63, mk_z: 3.9, mk_p_value: 0.0001, hr_canonical_p_value: 0.0002,
    hr_conservative_p_value: 0.0003, yw_canonical_p_value: 0.0002, lag1_autocorrelation: 0.1, ljung_box_p_value: 0.5,
    direction_sen: 'increasing', direction_ols: 'increasing', raw_p_value: 0.0001, adjusted_p_value: 0.0004, in_family: true,
    raw_status: 'significant_increasing', adjusted_status: 'significant_increasing', status: 'significant_increasing',
    status_reason: null,
    ...over,
  }
}

export function makeResponse(): SpatialTrendResponse {
  const cells = [
    makeCell(),
    makeCell({ id: '7.500_80.6250', latitude: 7.5, lat_min: 7.25, lat_max: 7.75, sen_slope: -0.05, ols_slope: -0.04, mk_s: -90,
      direction_sen: 'decreasing', direction_ols: 'decreasing', raw_status: 'significant_decreasing', adjusted_status: 'not_significant',
      status: 'not_significant', raw_p_value: 0.03, adjusted_p_value: 0.06 }),
    makeCell({ id: '8.000_80.6250', latitude: 8, overlap_fraction: 0.4, overlap_area_km2: 1520, data_status: 'insufficient_data',
      availability: 'insufficient', reason: 'Only 4 years', ols_slope: null, sen_slope: null, raw_p_value: null, adjusted_p_value: null,
      in_family: false, raw_status: 'insufficient_data', adjusted_status: 'insufficient_data', status: 'insufficient_data',
      direction_sen: null, direction_ols: null }),
  ]
  const cat = (count: number, t: number | null) => ({ count, area_km2: count * 3800, pct_of_included_cells: (count / 3) * 100,
    pct_of_included_area: 0, pct_of_tested_cells: t, pct_of_tested_area: t })
  const metadata = {
    data_mode: 'LIVE', provider: 'NASA POWER', dataset_title: 'x', api_version: 'v2',
    variable_id: 'air_temperature', variable_name: 'Air Temperature', parameter: 'T2M', long_name: 'Temperature at 2 Meters',
    community: 'AG', sources: ['MERRA2'], units_raw: 'C', unit_display: '°C', rate_unit: '°C/year', temporal_resolution: 'monthly',
    time_standard: 'LST', start_year: 2001, end_year: 2020, latest_complete_year: null,
    bbox: { lat_min: 6, lat_max: 9.5, lon_min: 79.5, lon_max: 82 }, request_bbox: { lat_min: 5.75, lat_max: 9.75, lon_min: 79.1875, lon_max: 82.3125 },
    returned_extent: null, region_area_km2: 1e5, analysed_area_km2: 1e5, land_fraction: null,
    grid_resolution: 'MERRA-2 native grid: 0.5° latitude × 0.625° longitude', n_cells_returned: 3, n_cells_used: 3, n_cells_excluded: 0,
    n_cells_outside: 0, n_duplicates: 0, aggregation_method: 'area-weighted', partial_cell_rule: 'overlap', coverage_threshold: 0.8,
    fill_value: -999, retrieved_at: '2026-11-14T00:00:00Z', served_from_cache: false,
    request_url: 'https://power.larc.nasa.gov/api/temporal/monthly/regional?x=1',
    documentation_url: 'https://power.larc.nasa.gov/docs/', parameter_docs_url: 'https://power.larc.nasa.gov/parameters/', source_note: 'n',
  } as RegionalMetadata
  return {
    metadata,
    config: {
      method: 'mann_kendall', method_label: 'Original Mann-Kendall', method_description: 'd', correction: 'fdr_bh',
      correction_label: 'Benjamini–Hochberg false discovery rate', alpha: 0.05, n_hypotheses: 2, min_valid_months_per_year: 10,
      min_years: 10, screening_alpha: 0.05, confidence_level: 0.95, raw_rule: 'p < α', adjusted_rule: 'q ≤ α', direction_basis: 'S',
      near_zero_rule: 'r',
      methods: [
        { id: 'mann_kendall', label: 'Original Mann-Kendall', short: 'Mann-Kendall', description: '' },
        { id: 'hamed_rao_canonical', label: 'Hamed–Rao (canonical)', short: 'Hamed–Rao (canonical)', description: '' },
      ],
      corrections: [{ id: 'none', label: 'none' }, { id: 'fdr_bh', label: 'BH' }, { id: 'fdr_by', label: 'BY' }],
      alphas: [0.01, 0.05, 0.1],
    },
    summary: {
      n_cells_total: 3, n_cells_included: 3, n_cells_excluded: 0, n_cells_analysed: 2, n_hypotheses: 2, n_raw_significant: 2,
      n_fdr_discoveries: 1, included_area_km2: 9120, tested_area_km2: 7600,
      categories: {
        significant_increasing: cat(1, 50), significant_decreasing: cat(0, 0), not_significant: cat(1, 50),
        insufficient_data: cat(1, null), not_testable: cat(0, null), excluded: { ...cat(0, null), pct_of_included_cells: null, pct_of_included_area: null },
      },
      n_positive_slope: 1, n_negative_slope: 1, n_near_zero_slope: 0, area_weighted_mean_ols_slope: -0.005,
      slope_identity_exact: false, alpha: 0.05,
    },
    regional_aggregate: { annual: [], ols_slope: -0.004, ols_p_value: 0.4, sen_slope: -0.003, mk_p_value: 0.5, evidence_label: 'No statistically significant trend', n_years: 20, analysis_message: null },
    cells,
    years: Array.from({ length: 20 }, (_, i) => 2001 + i),
    available: true,
    unavailable_reason: null,
    interpretation: ['The region contains both positive and negative local air temperature slopes.'],
    warnings: [],
  }
}
