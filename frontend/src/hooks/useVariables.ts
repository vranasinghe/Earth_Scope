import { api } from '../services/api'
import type { VariablesResponse } from '../types/api'
import { useApiResource } from './useApiResource'

const NO_PARAMS = {}
const fetchVariables = (_: object, signal: AbortSignal) => api.variables(signal)

/** Loads the variable catalogue (/api/variables). */
export function useVariables() {
  return useApiResource<object, VariablesResponse>(NO_PARAMS, fetchVariables, 'Could not load variables.')
}
