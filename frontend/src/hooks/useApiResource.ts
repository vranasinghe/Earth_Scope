import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../services/api'

interface Settled<T> {
  requestKey: string
  data: T | null
  error: ApiError | null
}

/**
 * Generic "fetch one resource for these params" hook shared by useVariables,
 * useAnalysis and useCompare.
 *
 * - Re-fetches only when the serialised params change or retry() is called.
 * - Aborts the in-flight request when params change or the component unmounts,
 *   so a slow, outdated response can never overwrite a newer one.
 * - Pass `params = null` to fetch nothing.
 */
export function useApiResource<P, T>(
  params: P | null,
  fetcher: (params: P, signal: AbortSignal) => Promise<T>,
  fallbackMessage: string,
) {
  const [attempt, setAttempt] = useState(0)
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const paramsKey = params === null ? null : JSON.stringify(params)
  const requestKey = paramsKey === null ? null : `${paramsKey}#${attempt}`

  useEffect(() => {
    if (paramsKey === null || requestKey === null) return
    const controller = new AbortController()
    fetcher(JSON.parse(paramsKey) as P, controller.signal)
      .then((data) => setSettled({ requestKey, data, error: null }))
      .catch((err: unknown) => {
        if ((err as Error).name === 'AbortError') return
        const error = err instanceof ApiError ? err : new ApiError(0, {}, fallbackMessage)
        setSettled({ requestKey, data: null, error })
      })
    return () => controller.abort()
    // Call sites pass stable module-level functions/strings, so these never retrigger on their own.
  }, [paramsKey, requestKey, fetcher, fallbackMessage])

  const retry = useCallback(() => setAttempt((a) => a + 1), [])
  const current = settled && settled.requestKey === requestKey ? settled : null
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: requestKey !== null && current === null,
    /** Most recent successful result for ANY params (lets a view keep showing it while new params load). */
    lastData: settled?.data ?? null,
    retry,
  }
}
