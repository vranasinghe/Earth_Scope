import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { AreaPreviewParams, AreaPreviewResponse, CountryListResponse } from '../types/area'
import { useApiResource } from './useApiResource'

const NO_PARAMS = {}
const fetchCountries = (_: object, signal: AbortSignal) => api.countries(signal)

/** Countries with an available boundary (geoBoundaries gbOpen; Natural Earth fallback). */
export function useCountries() {
  return useApiResource<object, CountryListResponse>(NO_PARAMS, fetchCountries, 'Could not load the country list.')
}

/** Boundary + metadata + preflight (cells, NASA requests, budgets) for a country or polygon. */
export function useAreaPreview(params: AreaPreviewParams | null) {
  return useApiResource<AreaPreviewParams, AreaPreviewResponse>(params, api.areaPreview, 'Could not check this area.')
}

/** Value that only updates after `delay` ms without changes (avoids a request per dragged vertex). */
export function useDebounced<T>(value: T, delay = 400): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return v
}
