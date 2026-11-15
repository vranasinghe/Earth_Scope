import { ArrowRight } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { AnalysisModeSwitch } from '../components/common/AnalysisModeSwitch'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { LocationPanel } from '../components/dashboard/LocationPanel'
import { TimeRangePanel } from '../components/dashboard/TimeRangePanel'
import { VariableSelector } from '../components/dashboard/VariableSelector'
import { useVariables } from '../hooks/useVariables'
import type { AnalysisParams, VariablesResponse } from '../types/api'
import { EMPTY_LOCATION, parseLocation } from '../utils/location'
import type { LocationValue } from '../utils/location'
import { fromSearch, knownPlaceName, toSearch } from '../utils/query'
import { parseCoordinate, validateLatitude, validateLongitude, validateYears } from '../utils/validation'

export default function Explore() {
  const { data, error, loading, retry } = useVariables()

  return (
    <div className="mx-auto max-w-7xl px-4 pb-10 pt-10 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">Explore a location</h1>
          <p className="measure mt-2 text-fg-muted">Test whether a variable has changed at one place on Earth, using the real monthly NASA record.</p>
        </div>
        <AnalysisModeSwitch />
      </header>
      <div className="mt-10">
        {loading && <LoadingState title="Loading the variable catalogue…" />}
        {error && (
          <ErrorState error={error} title="Could not connect to the Earth Scope backend" onRetry={retry}>
            <p className="w-full text-sm text-fg-subtle">
              Start it with <code className="font-mono text-fg">uvicorn app.main:app --port 8000</code> from the{' '}
              <code className="font-mono text-fg">backend</code> folder (see README).
            </p>
          </ErrorState>
        )}
        {data && <ExploreForm catalogue={data} />}
      </div>
    </div>
  )
}

function ExploreForm({ catalogue }: { catalogue: VariablesResponse }) {
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const initial = fromSearch(search)
  // Partial links (e.g. examples: ?variable=...&lat=...&lon=...) prefill what they provide.
  const requestedVariable = initial?.variable ?? search.get('variable')
  const [variable, setVariable] = useState(
    catalogue.variables.find((v) => v.id === requestedVariable)?.id ?? catalogue.variables[0].id,
  )
  // No default location: the page opens on a world map until the user chooses a point.
  const [location, setLocation] = useState<LocationValue>(() => {
    const la = initial?.latitude ?? (search.get('lat') !== null ? Number(search.get('lat')) : null)
    const lo = initial?.longitude ?? (search.get('lon') !== null ? Number(search.get('lon')) : null)
    if (la === null || lo === null || !Number.isFinite(la) || !Number.isFinite(lo)) return EMPTY_LOCATION
    return { latText: String(la), lonText: String(lo), placeName: knownPlaceName(la, lo, initial?.place ?? search.get('place') ?? undefined) ?? null }
  })
  const [start, setStart] = useState(initial?.startYear ?? catalogue.default_start_year)
  const [end, setEnd] = useState(initial?.endYear ?? catalogue.default_end_year)
  const [submitted, setSubmitted] = useState(false)

  const limits = {
    minYear: catalogue.min_year,
    maxYear: catalogue.max_year,
    minSpan: catalogue.min_year_span,
    defaultEnd: catalogue.default_end_year,
    minValidMonths: catalogue.min_valid_months_per_year,
  }
  const selected = catalogue.variables.find((v) => v.id === variable) ?? catalogue.variables[0]

  const point = parseLocation(location)
  const noLocation = location.latText.trim() === '' && location.lonText.trim() === ''
  const errors = [
    noLocation ? 'Choose a location: search, click the map, pick an example or enter coordinates.' : null,
    noLocation ? null : validateLatitude(parseCoordinate(location.latText)),
    noLocation ? null : validateLongitude(parseCoordinate(location.lonText)),
    validateYears(start, end, limits),
  ].filter((e): e is string => e !== null)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (errors.length || !point) return
    const params: AnalysisParams = {
      variable,
      latitude: point.lat,
      longitude: point.lon,
      startYear: start,
      endYear: end,
      place: location.placeName ?? undefined,
    }
    navigate(`/results${toSearch(params)}`)
  }

  const where = location.placeName ?? (point ? `${point.lat.toFixed(2)}, ${point.lon.toFixed(2)}` : 'no location yet')

  return (
    <form onSubmit={onSubmit} noValidate>
      <Step n={1} title="Variable" id="step-variable">
        <VariableSelector variables={catalogue.variables} selected={variable} onSelect={setVariable} />
        {(selected.notes.length > 0 || selected.land_only) && (
          <div className="mt-4 space-y-2">
            {selected.land_only && (
              <Notice tone="warn">
                {selected.name} is only meaningful over ice-free land. Over oceans, large lakes or ice sheets the analysis is refused and
                other variables are suggested.
              </Notice>
            )}
            {selected.notes.map((n) => (
              <Notice key={n}>{n}</Notice>
            ))}
          </div>
        )}
      </Step>

      <Step n={2} title="Location" id="step-location">
        <LocationPanel value={location} onChange={setLocation} showErrors={submitted} />
      </Step>

      <Step n={3} title="Period" id="step-time">
        <TimeRangePanel
          start={start}
          end={end}
          onChange={(s, e2) => {
            setStart(s)
            setEnd(e2)
          }}
          limits={limits}
          showErrors={submitted}
        />
      </Step>

      <div className="sticky bottom-0 z-[1000] -mx-4 mt-10 border-t border-line bg-page/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6">
        {submitted && errors.length > 0 && (
          <ul className="mb-3 space-y-1 text-sm text-danger" role="alert">
            {errors.map((er) => (
              <li key={er}>{er}</li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="min-w-0 text-[0.9375rem] text-fg-muted">
            <span className="font-semibold text-fg">{selected.name}</span> · {where} ·{' '}
            <span className="stat-num">
              {start}–{end}
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-4">
            <button type="submit" className="btn-primary px-6 text-base">
              Analyze trend <ArrowRight className="size-4" aria-hidden />
            </button>
          </div>
        </div>
      </div>
      <p className="mt-3 text-sm text-fg-subtle">Significance threshold α = {catalogue.significance_alpha}.</p>
    </form>
  )
}

function Step({ n, title, id, children }: { n: number; title: string; id: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t border-line py-8 first:border-t-0 first:pt-0 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-8">
      <h2 id={id} className="flex items-baseline gap-3 text-lg font-bold">
        <span className="stat-num text-sm font-medium text-accent">{n}</span>
        {title}
      </h2>
      <div className="min-w-0">{children}</div>
    </section>
  )
}
