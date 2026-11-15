import { api } from '../services/api'
import type { RegionalAnalysisResponse, RegionalConfig, RegionalParams } from '../types/api'
import { useApiResource } from './useApiResource'

const NO_PARAMS = {}
const fetchConfig = (_: object, signal: AbortSignal) => api.regionalConfig(signal)

/** Limits, defaults, variables and presets for regional analysis. */
export function useRegionalConfig() {
  return useApiResource<object, RegionalConfig>(NO_PARAMS, fetchConfig, 'Could not load the regional analysis settings.')
}

/** Regional area-weighted analysis (/api/regional/analyze). */
export function useRegionalAnalysis(params: RegionalParams | null) {
  return useApiResource<RegionalParams, RegionalAnalysisResponse>(params, api.regionalAnalyze, 'The regional analysis request failed.')
}
