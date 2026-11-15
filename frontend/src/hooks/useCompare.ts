import { api } from '../services/api'
import type { CompareParams, CompareResponse } from '../types/api'
import { useApiResource } from './useApiResource'

/** Fetches /api/compare (the backend fetches each location sequentially). */
export function useCompare(params: CompareParams | null) {
  return useApiResource<CompareParams, CompareResponse>(params, api.compare, 'The comparison request failed.')
}
