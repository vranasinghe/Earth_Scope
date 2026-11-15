import { Loader2, MapPin, Search, X } from 'lucide-react'
import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { api, ApiError } from '../../services/api'
import type { Place } from '../../types/api'
import { formatCoord } from '../../utils/format'
import { placeLabel } from '../../utils/location'

/**
 * Worldwide place search. Searches run only when the user submits (Enter or the
 * button) — OpenStreetMap Nominatim's usage policy does not allow autocomplete.
 * Requests go through the Earth Scope backend, which caches results and limits
 * the request rate.
 */
export function LocationSearch({ onSelect }: { onSelect: (place: Place) => void }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Place[] | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const listId = 'location-search-results'

  const submit = async () => {
    const q = query.trim()
    if (q.length < 2) {
      setError('Type at least 2 characters, e.g. "Nairobi" or "40.7128, -74.0060".')
      return
    }
    if (q === lastQuery && results) return // avoid duplicate requests
    controller.current?.abort()
    const c = new AbortController()
    controller.current = c
    setLoading(true)
    setError(null)
    try {
      const res = await api.geocodeSearch(q, c.signal)
      setResults(res.results)
      setLastQuery(q)
      setActive(0)
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      setResults(null)
      setError(err instanceof ApiError ? err.message : 'Location search failed. You can still click the map or type coordinates.')
    } finally {
      if (controller.current === c) setLoading(false)
    }
  }

  const choose = (p: Place) => {
    onSelect(p)
    setResults(null)
    setQuery(placeLabel(p))
    setLastQuery('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    // This component lives inside other forms (Explore), so it must not be a <form>
    // itself: Enter is handled here and never submits the surrounding form.
    if (e.key === 'Enter' && !(results?.length && query.trim() === lastQuery)) {
      e.preventDefault()
      void submit()
      return
    }
    if (!results?.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (a + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a - 1 + results.length) % results.length)
    } else if (e.key === 'Enter' && query.trim() === lastQuery) {
      e.preventDefault()
      choose(results[active])
    } else if (e.key === 'Escape') {
      setResults(null)
    }
  }

  return (
    <div className="relative">
      <div role="search" className="flex gap-2">
        <label htmlFor="location-search" className="sr-only">
          Search any location worldwide
        </label>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <input
            id="location-search"
            type="search"
            autoComplete="off"
            className="input pl-9 font-sans"
            placeholder="Search a place, or paste coordinates"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            aria-controls={listId}
            aria-expanded={Boolean(results)}
            aria-activedescendant={results?.length ? `${listId}-${active}` : undefined}
          />
          {query && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-fg-subtle hover:text-fg"
              aria-label="Clear search"
              onClick={() => {
                setQuery('')
                setResults(null)
                setError(null)
              }}
            >
              <X className="size-4" />
            </button>
          )}
        </div>
        <button type="button" className="btn-secondary shrink-0" disabled={loading} onClick={() => void submit()}>
          {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Search className="size-4" aria-hidden />}
          Search
        </button>
      </div>

      {error && (
        <p className="mt-2 text-sm text-warn" role="alert">
          {error}
        </p>
      )}

      {results && (
        <div className="absolute inset-x-0 top-full z-[1200] mt-2 overflow-hidden rounded-xl border border-line-strong bg-surface shadow-[var(--shadow-pop)]">
          {results.length === 0 ? (
            <p className="px-4 py-3 text-sm text-fg-muted">
              No places found for “{lastQuery}”. Try a different spelling, add the country, or click the map.
            </p>
          ) : (
            <ul id={listId} role="listbox" aria-label="Search results" className="max-h-72 overflow-y-auto py-1">
              {results.map((p, i) => (
                <li
                  key={`${p.latitude},${p.longitude},${i}`}
                  id={`${listId}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(p)}
                  className={`flex cursor-pointer items-start gap-3 px-4 py-2.5 text-sm ${i === active ? 'bg-raised' : ''}`}
                >
                  <MapPin className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-fg">
                      {p.name}
                      {p.place_type && p.place_type !== 'coordinates' && (
                        <span className="ml-2 text-xs font-normal text-fg-subtle">{p.place_type}</span>
                      )}
                    </span>
                    <span className="block truncate text-fg-muted">
                      {[p.region, p.country].filter(Boolean).join(', ') || p.display_name}
                    </span>
                    <span className="stat-num block text-xs text-fg-subtle">{formatCoord(p.latitude, p.longitude)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="border-t border-line px-4 py-1.5 text-[11px] text-fg-subtle">
            Search data © OpenStreetMap contributors (Nominatim)
          </p>
        </div>
      )}
    </div>
  )
}
