// TypeScript mirror of backend/app/models/spatial_trend_schemas.py

import type { RegionalMetadata, RegionalParams, StatisticsResult } from './api'
import type { AreaGeometry } from './area'

export type SpatialMethod = 'mann_kendall' | 'hamed_rao_canonical' | 'hamed_rao_conservative' | 'yue_wang_canonical'
export type SpatialCorrection = 'none' | 'fdr_bh' | 'fdr_by'
export type CellDataStatus = 'analysed' | 'insufficient_data' | 'no_variation' | 'calculation_failed' | 'excluded'
export type CellAvailability = 'complete' | 'partial' | 'insufficient' | 'missing' | 'excluded'
export type SignificanceStatus =
  | 'significant_increasing'
  | 'significant_decreasing'
  | 'not_significant'
  | 'insufficient_data'
  | 'not_testable'
  | 'excluded'
export type CellDirection = 'increasing' | 'decreasing' | 'near_zero'

export interface SpatialTrendCell {
  id: string
  latitude: number
  longitude: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  cell_area_km2: number
  overlap_area_km2: number
  overlap_fraction: number
  clip?: AreaGeometry | null
  weight: number
  valid_months: number
  total_months: number
  valid_years: number
  total_years: number
  period_mean: number | null
  data_status: CellDataStatus
  availability: CellAvailability
  reason: string | null
  first_year: number | null
  last_year: number | null
  ols_slope: number | null
  ols_intercept: number | null
  ols_p_value: number | null
  ols_r_squared: number | null
  ols_std_err: number | null
  ols_ci_lower: number | null
  ols_ci_upper: number | null
  hac_p_value: number | null
  sen_slope: number | null
  sen_ci_lower: number | null
  sen_ci_upper: number | null
  mk_s: number | null
  mk_tau: number | null
  mk_z: number | null
  mk_p_value: number | null
  hr_canonical_p_value: number | null
  hr_conservative_p_value: number | null
  yw_canonical_p_value: number | null
  lag1_autocorrelation: number | null
  ljung_box_p_value: number | null
  direction_sen: CellDirection | null
  direction_ols: CellDirection | null
  raw_p_value: number | null
  adjusted_p_value: number | null
  in_family: boolean
  raw_status: SignificanceStatus
  adjusted_status: SignificanceStatus
  status: SignificanceStatus
  status_reason: string | null
}

export interface MethodOption {
  id: SpatialMethod
  label: string
  short: string
  description: string
}

export interface SpatialTrendConfig {
  method: SpatialMethod
  method_label: string
  method_description: string
  correction: SpatialCorrection
  correction_label: string
  alpha: number
  n_hypotheses: number
  min_valid_months_per_year: number
  min_years: number
  screening_alpha: number
  confidence_level: number
  raw_rule: string
  adjusted_rule: string
  direction_basis: string
  near_zero_rule: string
  methods: MethodOption[]
  corrections: { id: SpatialCorrection; label: string }[]
  alphas: number[]
}

export interface CategorySummary {
  count: number
  area_km2: number
  pct_of_included_cells: number | null
  pct_of_included_area: number | null
  pct_of_tested_cells: number | null
  pct_of_tested_area: number | null
}

export interface SpatialSummary {
  n_cells_total: number
  n_cells_included: number
  n_cells_excluded: number
  n_cells_analysed: number
  n_hypotheses: number
  n_raw_significant: number
  n_fdr_discoveries: number | null
  included_area_km2: number
  tested_area_km2: number
  categories: Record<SignificanceStatus, CategorySummary>
  n_positive_slope: number
  n_negative_slope: number
  n_near_zero_slope: number
  area_weighted_mean_ols_slope: number | null
  slope_identity_exact: boolean
  alpha: number
}

export interface AnnualPoint {
  year: number
  value: number | null
  used_in_trend: boolean
}

export interface RegionalAggregate {
  annual: AnnualPoint[]
  ols_slope: number | null
  ols_p_value: number | null
  sen_slope: number | null
  mk_p_value: number | null
  evidence_label: string | null
  n_years: number
  analysis_message: string | null
}

export interface SpatialTrendResponse {
  metadata: RegionalMetadata
  config: SpatialTrendConfig
  summary: SpatialSummary
  regional_aggregate: RegionalAggregate | null
  cells: SpatialTrendCell[]
  years: number[]
  available: boolean
  unavailable_reason: string | null
  interpretation: string[]
  warnings: string[]
}

export interface SpatialCellDetail {
  metadata: RegionalMetadata
  config: SpatialTrendConfig
  cell: SpatialTrendCell
  annual: (AnnualPoint & { valid_months: number })[]
  statistics: StatisticsResult | null
  regional_annual: AnnualPoint[] | null
}

/** Statistical settings that need a backend request (cheap: per-cell statistics are cached server-side). */
export interface SpatialSettings {
  method: SpatialMethod
  correction: SpatialCorrection
  alpha: number
}

export interface SpatialParams extends RegionalParams, SpatialSettings {}

export interface SpatialCellParams extends SpatialParams {
  cellId: string
}

export type SpatialLayer = 'magnitude' | 'direction' | 'significance' | 'availability'
export type SlopeEstimator = 'sen' | 'ols'
export type SignificanceBasis = 'adjusted' | 'raw'
