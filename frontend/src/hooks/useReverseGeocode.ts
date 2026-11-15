import { useEffect, useState } from 'react'
import { api } from '../services/api'
import type { Place } from '../types/api'

interface Settled {
  key: string
  place: Place | null
}

/**
 * Readable place name for a point (debounced; backend caches and rate-limits).
 * Returns `undefined` while unknown/loading, `null` when there is no named place
 * (e.g. open ocean). Failures are silent — the name is a convenience only.
 */
export function useReverseGeocode(lat: number | null, lon: number | null, enabled = true): Place | null | undefined {
  const key = enabled && lat !== null && lon !== null ? `${lat.toFixed(3)},${lon.toFixed(3)}` : null
  const [settled, setSettled] = useState<Settled | null>(null)

  useEffect(() => {
    if (!key) return
    const [la, lo] = key.split(',').map(Number)
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api
        .geocodeReverse(la, lo, controller.signal)
        .then((r) => setSettled({ key, place: r.place }))
        .catch((err: unknown) => {
          if ((err as Error).name !== 'AbortError') setSettled({ key, place: null })
        })
    }, 700)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [key])

  if (!key || !settled || settled.key !== key) return undefined
  return settled.place
}
