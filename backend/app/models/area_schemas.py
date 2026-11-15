"""Pydantic models for country boundaries and country / custom-polygon analysis requests."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.regional_schemas import BBoxModel, BoundaryInfo


class CountryListItem(BaseModel):
    iso3: str
    name: str
    source: str
    status: str | None = None


class CountryListResponse(BaseModel):
    countries: list[CountryListItem]
    default_source: str = "geoBoundaries gbOpen ADM0"
    fallback_source: str = "Natural Earth 1:50m Admin-0 v5.1.2 (only where gbOpen has no boundary)"


class TileEstimate(BaseModel):
    tile: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    cells: int


class Preflight(BaseModel):
    valid: bool
    available: bool
    reasons: list[str]
    suggestions: list[str]
    n_cells: int
    n_tiles: int
    n_months: int
    n_values: int
    estimated_seconds: float
    estimated_spatial_seconds: float
    estimated_memory_mb: float
    mean_cell_overlap_km2: float
    small_area_warning: str | None
    tiles: list[TileEstimate]
    limits: dict[str, int]
    grid: str


class AreaDescription(BaseModel):
    kind: Literal["country", "polygon"]
    name: str
    iso3: str | None
    geometry_id: str
    geometry: dict[str, Any] = Field(..., description="Display GeoJSON (lightly simplified); calculations use the full geometry")
    bbox: BBoxModel
    area_km2: float = Field(..., description="Equal-area (spherical) area — consistent with the cell weights")
    geodesic_area_km2: float = Field(..., description="WGS84 ellipsoidal geodesic area (pyproj), for reference")
    n_components: int
    n_vertices: int
    boundary: BoundaryInfo | None
    notes: list[str]


class AreaPreviewResponse(BaseModel):
    area: AreaDescription
    preflight: Preflight
    variable: str
    start_year: int
    end_year: int


class AreaRequest(BaseModel):
    iso3: str | None = Field(None, description="ISO 3166-1 alpha-3 code from /api/boundaries/countries")
    geometry: dict[str, Any] | None = Field(None, description="GeoJSON Polygon / MultiPolygon / Feature(Collection), WGS84 lon/lat")
    name: str | None = Field(None, max_length=120)
    variable: str
    start_year: int | None = None
    end_year: int | None = None
    coverage_threshold: float | None = None


class AreaSpatialRequest(AreaRequest):
    method: str = "mann_kendall"
    correction: str = "fdr_bh"
    alpha: float = 0.05


class AreaCellRequest(AreaSpatialRequest):
    cell_id: str
