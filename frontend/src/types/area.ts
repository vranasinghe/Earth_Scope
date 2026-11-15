// TypeScript mirror of backend/app/models/area_schemas.py (country & custom-polygon areas).

import type { BBox } from './api'

export type Position = [number, number] // [lon, lat] (GeoJSON order)
export interface PolygonGeometry {
  type: 'Polygon'
  coordinates: Position[][]
}
export interface MultiPolygonGeometry {
  type: 'MultiPolygon'
  coordinates: Position[][][]
}
export type AreaGeometry = PolygonGeometry | MultiPolygonGeometry

/** What the user selected: a country from the catalogue, or a drawn / uploaded polygon. */
export type AreaRef = { kind: 'country'; iso3: string } | { kind: 'polygon'; geometry: AreaGeometry; name: string }

export interface BoundaryInfo {
  source: string
  dataset: string
  version: string
  boundary_id: string
  year_represented: string | null
  license: string | null
  license_source: string | null
  upstream_source: string | null
  build_date: string | null
  attribution: string
  status: string | null
  reported_area_km2: number | null
  geometry_url: string | null
}

export interface TileRequest {
  tile: string
  lat_min: number
  lat_max: number
  lon_min: number
  lon_max: number
  url: string | null
  retrieved_at: string
  from_cache: boolean
  attempts: number
  cells_returned: number
  cells_used: number
}

export interface CountryListItem {
  iso3: string
  name: string
  source: string
  status: string | null
}

export interface CountryListResponse {
  countries: CountryListItem[]
  default_source: string
  fallback_source: string
}

export interface Preflight {
  valid: boolean
  available: boolean
  reasons: string[]
  suggestions: string[]
  n_cells: number
  n_tiles: number
  n_months: number
  n_values: number
  estimated_seconds: number
  estimated_spatial_seconds: number
  estimated_memory_mb: number
  mean_cell_overlap_km2: number
  small_area_warning: string | null
  tiles: { tile: string; lat_min: number; lat_max: number; lon_min: number; lon_max: number; cells: number }[]
  limits: Record<string, number>
  grid: string
}

export interface AreaDescription {
  kind: 'country' | 'polygon'
  name: string
  iso3: string | null
  geometry_id: string
  geometry: AreaGeometry
  bbox: BBox
  area_km2: number
  geodesic_area_km2: number
  n_components: number
  n_vertices: number
  boundary: BoundaryInfo | null
  notes: string[]
}

export interface AreaPreviewResponse {
  area: AreaDescription
  preflight: Preflight
  variable: string
  start_year: number
  end_year: number
}

export interface AreaPreviewParams {
  area: AreaRef
  variable: string
  startYear: number
  endYear: number
}
