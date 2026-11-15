// Types mirroring the backend Pydantic schemas (backend/app/models/schemas.py).

import type { AreaGeometry, AreaRef, BoundaryInfo, TileRequest } from './area'

export type DataMode = 'LIVE'
export type MonthlyStatus = 'valid' | 'missing' | 'invalid'
export type AnnualStatus = 'complete' | 'incomplete' | 'missing'
export type Direction = 'increasing' | 'decreasing' | 'no change'
export type EvidenceCategory =
  | 'significant_increasing'
  | 'significant_decreasing'
  | 'not_significant'
  | 'mixed'

export interface VariableInfo {
  id: string
  name: string
  parameter: string
  community: string
  category: string
  description: string
  purpose: string
  expected_unit: string
  unit_display: string
  rate_unit: string
  source_note: string
  spatial_resolution: string
  notes: string[]
  temporal_resolution: 'monthly'
  data_source: string
  supported_communities: string[]
  available_temporal_resolutions: string[]
  coverage_start_year: number
  geographic_coverage: string
  land_only: boolean
  alternatives: string[]
}

export interface VariablesResponse {
  variables: VariableInfo[]
  min_year: number
  max_year: number
  default_start_year: number
  default_end_year: number
  min_year_span: number
  min_valid_months_per_year: number
  min_annual_records: number
  significance_alpha: number
  documentation_url: string
  parameter_docs_url: string
}

/** MERRA-2 cell (0.5° × 0.625°) whose values NASA POWER returns for the point. */
export interface GridCell {
  center_latitude: number
  center_longitude: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  lat_step: number
  lon_step: number
}

export interface DatasetMetadata {
  data_mode: DataMode
  provider: string
  dataset_title: string | null
  api_version: string | null
  variable_id: string
  variable_name: string
  parameter: string
  long_name: string | null
  community: string
  sources: string[]
  units_raw: string | null
  unit_display: string
  rate_unit: string
  latitude_requested: number
  longitude_requested: number
  latitude_returned: number | null
  longitude_returned: number | null
  /** Elevation of the grid cell, as reported by NASA. */
  elevation_m: number | null
  grid_cell: GridCell | null
  spatial_resolution: string
  temporal_resolution: 'monthly'
  time_standard: string | null
  start_year: number
  end_year: number
  fill_value: number | null
  latest_complete_year: number | null
  retrieved_at: string
  served_from_cache: boolean
  request_url: string | null
  documentation_url: string
  parameter_docs_url: string
  source_note: string
}

export interface MonthlyRecord {
  date: string
  year: number
  month: number
  value: number | null
  status: MonthlyStatus
}

export interface AnnualRecord {
  year: number
  value: number | null
  valid_months: number
  total_months: number
  status: AnnualStatus
  used_in_trend: boolean
}

export interface DataSummary {
  n_monthly_total: number
  n_monthly_valid: number
  n_monthly_missing: number
  n_annual_total: number
  n_annual_complete: number
  n_annual_used: number
  min_valid_months_per_year: number
}

export interface TrendPoint {
  year: number
  value: number
}

export interface RegressionResult {
  slope: number
  intercept: number
  p_value: number
  r_squared: number
  r: number
  std_err: number
  ci_lower: number
  ci_upper: number
  confidence_level: number
  n: number
  degrees_of_freedom: number
  significant: boolean
  direction: Direction
  slope_per_decade: number
  trend_line: TrendPoint[]
}

export interface MannKendallResult {
  trend: Direction
  significant: boolean
  p_value: number
  z: number
  tau: number
  s: number
  var_s: number
  n: number
}

export interface SensSlopeResult {
  slope: number
  intercept: number
  slope_per_decade: number
  direction: Direction
  n_pairs: number
  /** Sen (1968) non-parametric confidence interval (per year). */
  ci_lower: number | null
  ci_upper: number | null
  confidence_level: number | null
  ci_method: string | null
}

export interface EvidenceSummary {
  category: EvidenceCategory
  label: string
  explanation: string
}

export interface AcfPoint {
  lag: number
  value: number
  outside_bound: boolean
}

export interface AutocorrelationDiagnostics {
  basis: string
  n: number
  lag1: number
  lag1_assessment: 'not_significant' | 'significant_positive' | 'significant_negative'
  bound: number
  acf: AcfPoint[]
  ljung_box: { q: number; lags: number; p_value: number; significant: boolean }
  has_gaps: boolean
  notes: string[]
}

export interface ModifiedMannKendallResult {
  method: string
  available: boolean
  s: number
  var_s_original: number
  var_s: number | null
  /** Estimated factor before the conservative floor at 1. */
  raw_correction_factor: number
  /** Applied factor (never below 1). */
  correction_factor: number
  /** True when a variance reduction was estimated but not applied. */
  reduction_suppressed: boolean
  /** Unmodified published method (raw factor, no floor). Null when not computable. */
  canonical_var_s: number | null
  canonical_z: number | null
  canonical_p_value: number | null
  canonical_significant: boolean | null
  effective_n: number | null
  z: number | null
  p_value: number | null
  significant: boolean | null
  trend: Direction | null
  n: number
  lags_considered: number
  rank_acf: AcfPoint[]
  significant_lags: number[]
  correction_applied: boolean
  reliable: boolean
  reliability_note: string | null
  unavailable_reason: string | null
}

export interface HacRegressionResult {
  method: string
  slope: number
  std_err: number
  t_statistic: number
  p_value: number
  ci_lower: number
  ci_upper: number
  confidence_level: number
  max_lags: number
  kernel: string
  significant: boolean
  degrees_of_freedom: number
}

export interface AdvancedStatistics {
  autocorrelation: AutocorrelationDiagnostics
  modified_mann_kendall: ModifiedMannKendallResult
  yue_wang_sensitivity: ModifiedMannKendallResult
  regression_hac: HacRegressionResult
  robust_evidence: EvidenceSummary
}

export interface StatisticsResult {
  alpha: number
  n_years: number
  first_year: number
  last_year: number
  regression: RegressionResult
  mann_kendall: MannKendallResult
  sens_slope: SensSlopeResult
  evidence: EvidenceSummary
  /** Autocorrelation-aware methods (absent from older responses). */
  advanced?: AdvancedStatistics | null
}

export interface Interpretation {
  headline: string
  paragraphs: string[]
  caveats: string[]
  /** Rule-based text for the advanced statistics. */
  advanced?: string[]
}

export interface DataResponse {
  metadata: DatasetMetadata
  monthly: MonthlyRecord[]
  annual: AnnualRecord[]
  summary: DataSummary
  warnings: string[]
}

export interface AnalysisResponse extends DataResponse {
  statistics: StatisticsResult | null
  analysis_message: string | null
  /** e.g. INSUFFICIENT_DATA_FOR_ANALYSIS */
  analysis_error: string | null
  interpretation: Interpretation
}

export interface ApiErrorBody {
  error: string
  message: string
  details: string[]
  retryable: boolean
  suggested_variables?: string[]
}

// --- Location search ------------------------------------------------------

export interface Place {
  name: string
  display_name: string
  country: string | null
  country_code: string | null
  region: string | null
  place_type: string | null
  latitude: number
  longitude: number
  source: string
}

export interface GeocodeSearchResponse {
  query: string
  results: Place[]
  attribution: string
}

export interface ReverseGeocodeResponse {
  latitude: number
  longitude: number
  place: Place | null
  attribution: string
}

// --- Multi-location comparison ---------------------------------------------

export interface CompareLocationInput {
  latitude: number
  longitude: number
  label: string
}

export interface CompareLocationResult {
  label: string
  latitude: number
  longitude: number
  ok: boolean
  error: ApiErrorBody | null
  metadata: DatasetMetadata | null
  annual: AnnualRecord[]
  summary: DataSummary | null
  statistics: StatisticsResult | null
  analysis_message: string | null
  analysis_error: string | null
  warnings: string[]
}

export interface CompareResponse {
  data_mode: DataMode
  variable_id: string
  variable_name: string
  parameter: string
  unit_display: string
  rate_unit: string
  start_year: number
  end_year: number
  alpha: number
  locations: CompareLocationResult[]
  summary: { lines: string[]; caveats: string[] }
}

export interface CompareParams {
  variable: string
  locations: CompareLocationInput[]
  startYear: number
  endYear: number
}

/** Minimal time-series shape shared by point and regional results (charts, table). */
export interface SeriesView {
  metadata: { unit_display: string; start_year: number; end_year: number; variable_name: string; parameter: string }
  monthly: { date: string; year: number; month: number; value: number | null; status: string; spatial_sd?: number | null }[]
  annual: { year: number; value: number | null; valid_months: number; used_in_trend: boolean; status: string; spatial_sd?: number | null }[]
  summary: { n_monthly_missing: number; min_valid_months_per_year: number }
  statistics: StatisticsResult | null
}

export interface AnalysisParams {
  variable: string
  latitude: number
  longitude: number
  startYear: number
  endYear: number
  /** Optional human-readable place name (from search or presets); display only. */
  place?: string
}

// --- Regional (bounding-box) analysis ----------------------------------------

export interface BBox {
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
}

export interface RegionalMetadata {
  data_mode: DataMode
  provider: string
  dataset_title: string | null
  api_version: string | null
  variable_id: string
  variable_name: string
  parameter: string
  long_name: string | null
  community: string
  sources: string[]
  units_raw: string | null
  unit_display: string
  rate_unit: string
  temporal_resolution: 'monthly'
  time_standard: string | null
  start_year: number
  end_year: number
  latest_complete_year: number | null
  bbox: BBox
  request_bbox: BBox
  returned_extent: BBox | null
  region_area_km2: number
  analysed_area_km2: number
  land_fraction: number | null
  grid_resolution: string
  n_cells_returned: number
  n_cells_used: number
  n_cells_excluded: number
  n_cells_outside: number
  n_duplicates: number
  aggregation_method: string
  partial_cell_rule: string
  coverage_threshold: number
  fill_value: number | null
  retrieved_at: string
  served_from_cache: boolean
  request_url: string | null
  documentation_url: string
  parameter_docs_url: string
  source_note: string
  // --- Country / custom polygon (absent or default for rectangles) ---
  area_mode?: 'rectangle' | 'country' | 'polygon'
  area_name?: string | null
  iso3?: string | null
  geometry_id?: string | null
  geometry?: AreaGeometry | null
  boundary?: BoundaryInfo | null
  geometry_notes?: string[]
  polygon_area_km2?: number | null
  geodesic_area_km2?: number | null
  n_components?: number | null
  n_vertices?: number | null
  request_manifest?: TileRequest[] | null
  n_tiles?: number | null
  n_cells_missing_from_response?: number | null
  grid_representability?: number | null
  /** 'background' when the result was produced by a durable background job (scientifically identical). */
  execution_mode?: 'synchronous' | 'background'
  job_id?: string | null
  analysis_software_version?: string | null
  published_at?: string | null
}

export interface RegionalMonthlyRecord {
  date: string
  year: number
  month: number
  value: number | null
  computed_mean: number | null
  status: 'valid' | 'insufficient_coverage' | 'missing'
  spatial_sd: number | null
  min_value: number | null
  max_value: number | null
  valid_cells: number
  missing_cells: number
  valid_area_km2: number
  coverage: number
}

export interface RegionalAnnualRecord {
  year: number
  value: number | null
  valid_months: number
  total_months: number
  status: AnnualStatus
  used_in_trend: boolean
  spatial_sd: number | null
}

export interface GridCellInfo {
  latitude: number
  longitude: number
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  cell_area_km2: number
  overlap_area_km2: number
  overlap_fraction: number
  weight: number
  status: 'valid' | 'partial' | 'missing' | 'excluded'
  exclusion_reason: string | null
  valid_months: number
  total_months: number
  period_mean: number | null
  annual: (number | null)[]
  /** Polygon mode: the part of the cell inside the area (null = whole cell). */
  clip?: AreaGeometry | null
}

export interface RegionalAnalysisResponse {
  metadata: RegionalMetadata
  monthly: RegionalMonthlyRecord[]
  annual: RegionalAnnualRecord[]
  summary: {
    n_monthly_total: number
    n_monthly_valid: number
    n_monthly_missing: number
    n_monthly_insufficient: number
    n_annual_total: number
    n_annual_complete: number
    n_annual_used: number
    min_valid_months_per_year: number
    mean_coverage: number
  }
  cells: GridCellInfo[]
  cell_years: number[]
  warnings: string[]
  statistics: StatisticsResult | null
  analysis_message: string | null
  analysis_error: string | null
  interpretation: Interpretation
}

export interface RegionPreset {
  name: string
  description: string
  bbox: BBox
}

export interface RegionalConfig {
  variables: VariableInfo[]
  min_span_deg: number
  max_span_deg: number
  nasa_min_span_deg: number
  nasa_max_span_deg: number
  default_coverage_threshold: number
  min_land_fraction: number
  grid_lat_step: number
  grid_lon_step: number
  min_year: number
  max_year: number
  default_start_year: number
  default_end_year: number
  min_year_span: number
  presets: RegionPreset[]
}

export interface RegionalParams {
  variable: string
  bbox: BBox
  startYear: number
  endYear: number
  coverageThreshold: number
  /** Country or custom polygon; absent = the rectangle `bbox`. */
  area?: AreaRef
  /** Completed background job whose stored result is shown (the other fields are then placeholders). */
  jobId?: string
}
