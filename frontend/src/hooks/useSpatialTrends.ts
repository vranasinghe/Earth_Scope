import { api } from '../services/api'
import type { SpatialCellDetail, SpatialCellParams, SpatialParams, SpatialTrendResponse } from '../types/spatial'
import { useApiResource } from './useApiResource'

/** Per-cell trends + multiple-testing-corrected significance (/api/regional/spatial-trends). */
export function useSpatialTrends(params: SpatialParams | null) {
  return useApiResource<SpatialParams, SpatialTrendResponse>(params, api.spatialTrends, 'The spatial trend request failed.')
}

/** Full statistics and annual series for one grid cell. */
export function useSpatialCell(params: SpatialCellParams | null) {
  return useApiResource<SpatialCellParams, SpatialCellDetail>(params, api.spatialCell, 'Could not load this grid cell.')
}
