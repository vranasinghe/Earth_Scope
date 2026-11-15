import { api } from '../services/api'
import type { AnalysisParams, AnalysisResponse } from '../types/api'
import { useApiResource } from './useApiResource'

/** Fetches /api/analyze for the given params; re-runs when params change or on retry(). */
export function useAnalysis(params: AnalysisParams | null) {
  return useApiResource<AnalysisParams, AnalysisResponse>(params, api.analyze, 'The analysis request failed.')
}
