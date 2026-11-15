import { ArrowRight, ArrowUpRight, Pencil, Plus, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { CompareChart } from '../components/charts/CompareChart'
import { DataModeBadge } from '../components/common/DataModeBadge'
import { SectionHeading } from '../components/common/SectionHeading'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { LocationPanel } from '../components/dashboard/LocationPanel'
import { TimeRangePanel } from '../components/dashboard/TimeRangePanel'
import { COMPARE_SERIES } from '../constants/compare'
import { COMPARE_EXAMPLE, presetLabel } from '../constants/locations'
import { useAiPageContext } from '../context/aiChatContext'
import { useCompare } from '../hooks/useCompare'
import { useVariables } from '../hooks/useVariables'
import type { CompareLocationInput, CompareParams, CompareResponse, StatisticsResult, VariablesResponse } from '../types/api'
import { formatCoord, formatP, formatSigned } from '../utils/format'
import { EMPTY_LOCATION, parseLocation } from '../utils/location'
import type { LocationValue } from '../utils/location'
import { fromCompareSearch, toCompareSearch, toSearch } from '../utils/query'
import { compareContext } from '../utils/buildAiContext'
import { validateYears } from '../utils/validation'

const MAX_LOCATIONS = 3

export default function Compare() {
  const [search] = useSearchParams()
  const params = useMemo(() => fromCompareSearch(search), [search])
  const vars = useVariables()

  return (
    <div className="mx-auto max-w-7xl px-4 pb-10 pt-10 sm:px-6">
      {vars.loading && <LoadingState title="Loading the variable catalogue…" />}
      {vars.error && <ErrorState error={vars.error} title="Could not connect to the Earth Scope backend" onRetry={vars.retry} />}
      {vars.data && (params ? <CompareResults params={params} catalogue={vars.data} /> : <CompareSetup catalogue={vars.data} />)}
    </div>
  )
}

function CompareSetup({ catalogue }: { catalogue: VariablesResponse }) {
  const navigate = useNavigate()
  const [search] = useSearchParams()
  // "Edit comparison" links come back here with the same parameters under edit=…
  const prefill = useMemo(() => fromCompareSearch(new URLSearchParams(search.get('edit') ?? '')), [search])
  const [variable, setVariable] = useState(prefill?.variable ?? catalogue.variables[0].id)
  const [start, setStart] = useState(prefill?.startYear ?? catalogue.default_start_year)
  const [end, setEnd] = useState(prefill?.endYear ?? catalogue.default_end_year)
  const [locations, setLocations] = useState<CompareLocationInput[]>(prefill?.locations ?? [])
  const [current, setCurrent] = useState<LocationValue>(EMPTY_LOCATION)
  const [submitted, setSubmitted] = useState(false)

  const limits = {
    minYear: catalogue.min_year,
    maxYear: catalogue.max_year,
    minSpan: catalogue.min_year_span,
    defaultEnd: catalogue.default_end_year,
    minValidMonths: catalogue.min_valid_months_per_year,
  }
  const point = parseLocation(current)
  const selected = catalogue.variables.find((v) => v.id === variable) ?? catalogue.variables[0]
  const duplicate = point !== null && locations.some((l) => l.latitude === point.lat && l.longitude === point.lon)
  const yearError = validateYears(start, end, limits)
  const canCompare = locations.length >= 2 && !yearError
  const full = locations.length >= MAX_LOCATIONS

  const add = () => {
    if (!point || duplicate || full) return
    setLocations((ls) => [...ls, { latitude: point.lat, longitude: point.lon, label: current.placeName ?? formatCoord(point.lat, point.lon, 2) }])
    setCurrent(EMPTY_LOCATION)
  }
  const go = (p: CompareParams) => navigate(`/compare${toCompareSearch(p)}`)
  const example = () =>
    go({
      variable: COMPARE_EXAMPLE.variable,
      startYear: catalogue.default_start_year,
      endYear: catalogue.default_end_year,
      locations: COMPARE_EXAMPLE.locations.map((p) => ({ latitude: p.latitude, longitude: p.longitude, label: presetLabel(p) })),
    })

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">Compare places</h1>
          <p className="measure mt-2 text-fg-muted">One variable at two or three places, each tested separately with the same method, period and units.</p>
        </div>
        <button type="button" className="btn-ghost text-sm" onClick={example}>
          Try New York, Tokyo and Sydney <ArrowRight className="size-4" aria-hidden />
        </button>
      </header>

      {/* Slots: progress toward 2–3 places is visible at a glance */}
      <ol className="mt-8 grid gap-3 sm:grid-cols-3" aria-label="Places in this comparison">
        {Array.from({ length: MAX_LOCATIONS }, (_, i) => {
          const l = locations[i]
          return l ? (
            <li key={`${l.latitude},${l.longitude}`} className="flex items-center gap-3 rounded-lg border border-line-strong bg-surface px-3.5 py-3">
              <SeriesDot i={i} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold">{l.label}</span>
                <span className="stat-num block text-xs text-fg-subtle">{formatCoord(l.latitude, l.longitude, 3)}</span>
              </span>
              <button
                type="button"
                className="rounded-md p-1.5 text-fg-subtle hover:bg-raised hover:text-danger"
                aria-label={`Remove ${l.label}`}
                onClick={() => setLocations((ls) => ls.filter((_, k) => k !== i))}
              >
                <X className="size-4" aria-hidden />
              </button>
            </li>
          ) : (
            <li key={`empty-${i}`} className="flex items-center gap-3 rounded-lg border border-dashed border-line-strong px-3.5 py-3 text-fg-subtle">
              <span className="stat-num grid size-6 place-items-center rounded-full border border-dashed border-line-strong text-xs">{i + 1}</span>
              <span className="text-sm">{i < 2 ? 'Add a place' : 'Optional third place'}</span>
            </li>
          )
        })}
      </ol>

      <div className="mt-8 space-y-0">
        <Row title="Variable">
          <div className="seg" role="radiogroup" aria-label="Variable">
            {catalogue.variables.map((v) => (
              <button key={v.id} type="button" role="radio" aria-checked={v.id === variable} onClick={() => setVariable(v.id)} className="seg-item">
                {v.name}
              </button>
            ))}
          </div>
          {selected.land_only && (
            <p className="mt-3 text-sm text-warn">{selected.name} is only meaningful over ice-free land; ocean, lake or ice-sheet places are reported as not supported.</p>
          )}
        </Row>

        <Row title="Add places">
          {!full ? (
            <LocationPanel
              value={current}
              onChange={setCurrent}
              showErrors={false}
              extraPoints={locations.map((l, i) => ({ ...l, color: COMPARE_SERIES[i].color }))}
              actions={
                <>
                  <button type="button" className="btn-primary w-full" disabled={!point || duplicate} onClick={add}>
                    <Plus className="size-4" aria-hidden /> Add to comparison
                  </button>
                  {duplicate && <p className="mt-2 text-sm text-warn">This point is already in the comparison.</p>}
                </>
              }
            />
          ) : (
            <Notice>All three places are set. Remove one above to choose another.</Notice>
          )}
        </Row>

        <Row title="Period">
          <TimeRangePanel
            start={start}
            end={end}
            onChange={(s, e) => {
              setStart(s)
              setEnd(e)
            }}
            limits={limits}
            showErrors={submitted}
          />
        </Row>
      </div>

      <div className="sticky bottom-0 z-[1000] -mx-4 mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-line bg-page/90 px-4 py-4 backdrop-blur-md sm:-mx-6 sm:px-6">
        <p className="text-[0.9375rem] text-fg-muted">
          <span className="stat-num font-semibold text-fg">{locations.length}</span> of {MAX_LOCATIONS} places
          {locations.length < 2 ? ` · add ${2 - locations.length} more to compare` : ' · places are fetched in parallel from NASA POWER'}
        </p>
        <button
          type="button"
          className="btn-primary px-6 text-base"
          disabled={locations.length < 2}
          onClick={() => {
            setSubmitted(true)
            if (canCompare) go({ variable, startYear: start, endYear: end, locations })
          }}
        >
          Compare places <ArrowRight className="size-4" aria-hidden />
        </button>
      </div>
    </>
  )
}

function Row({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-line py-8 md:grid-cols-[11rem_minmax(0,1fr)] md:gap-8">
      <h2 className="text-lg font-bold">{title}</h2>
      <div className="min-w-0">{children}</div>
    </section>
  )
}

function SeriesDot({ i }: { i: number }) {
  return (
    <span className="stat-num grid size-6 shrink-0 place-items-center rounded-full text-xs font-bold text-[#08101c]" style={{ background: COMPARE_SERIES[i].color }}>
      {i + 1}
    </span>
  )
}

function CompareResults({ params, catalogue }: { params: CompareParams; catalogue: VariablesResponse }) {
  const { data, error, loading, retry } = useCompare(params)
  const editLink = `/compare?edit=${encodeURIComponent(toCompareSearch(params))}`
  const name = catalogue.variables.find((v) => v.id === params.variable || v.parameter === params.variable)?.name ?? params.variable
  useAiPageContext(data ? compareContext(params, name) : null)

  return (
    <div>
      <Link to={editLink} className="btn-ghost -ml-3 mb-6">
        <Pencil className="size-4" aria-hidden /> Edit comparison
      </Link>
      {loading && <LoadingState title={`Retrieving ${name} for ${params.locations.length} places…`} steps={params.locations.map((l) => l.label)} />}
      {error && (
        <ErrorState error={error} title="The comparison could not be completed" onRetry={error.retryable ? retry : undefined}>
          <Link to={editLink} className="btn-secondary">
            <Pencil className="size-4" aria-hidden /> Edit comparison
          </Link>
        </ErrorState>
      )}
      {data && <CompareView data={data} />}
    </div>
  )
}

type StatRow = { label: string; value: (s: StatisticsResult) => string | null }

const ROWS: StatRow[] = [
  { label: 'OLS slope', value: (s) => formatSigned(s.regression.slope) },
  { label: 'OLS 95% CI', value: (s) => `${formatSigned(s.regression.ci_lower)} to ${formatSigned(s.regression.ci_upper)}` },
  { label: 'Sen’s slope', value: (s) => formatSigned(s.sens_slope.slope) },
  { label: 'Sen 95% CI', value: (s) => (s.sens_slope.ci_lower !== null && s.sens_slope.ci_upper !== null ? `${formatSigned(s.sens_slope.ci_lower)} to ${formatSigned(s.sens_slope.ci_upper)}` : '—') },
  { label: 'Mann-Kendall p', value: (s) => formatP(s.mann_kendall.p_value) },
  { label: 'Modified MK p (Hamed–Rao)', value: (s) => (s.advanced?.modified_mann_kendall.available ? formatP(s.advanced.modified_mann_kendall.p_value) : '—') },
  { label: 'Regression p · R²', value: (s) => `${formatP(s.regression.p_value)} · ${s.regression.r_squared.toFixed(2)}` },
  { label: 'Years used', value: (s) => String(s.n_years) },
]

function CompareView({ data }: { data: CompareResponse }) {
  return (
    <div className="space-y-14">
      <header className="border-b border-line pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">{data.variable_name}, compared</h1>
            <p className="mt-2 text-fg-muted">
              <span className="stat-num">
                {data.start_year}–{data.end_year}
              </span>{' '}
              · annual means of monthly NASA POWER {data.parameter} · rates in {data.rate_unit}
            </p>
          </div>
          <DataModeBadge mode={data.data_mode} size="lg" />
        </div>
      </header>

      <section>
        <SectionHeading title="Side by side" description={`Each place is tested independently at α = ${data.alpha}.`} />
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[40rem] text-[0.9375rem]">
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="w-56 px-5 py-4 text-left text-sm font-semibold text-fg-subtle">
                  <span className="sr-only">Statistic</span>
                </th>
                {data.locations.map((loc, i) => (
                  <th key={i} scope="col" className="px-5 py-4 text-left align-top">
                    <span className="flex items-start gap-2.5">
                      <SeriesDot i={i} />
                      <span className="min-w-0">
                        <span className="block font-bold text-fg">{loc.label}</span>
                        <span className="stat-num block text-xs font-normal text-fg-subtle">
                          {loc.metadata?.grid_cell
                            ? `cell ${formatCoord(loc.metadata.grid_cell.center_latitude, loc.metadata.grid_cell.center_longitude, 3)}`
                            : formatCoord(loc.latitude, loc.longitude, 3)}
                        </span>
                      </span>
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              <tr>
                <th scope="row" className="px-5 py-3 text-left font-semibold">
                  Evidence
                </th>
                {data.locations.map((loc, i) => {
                  const s = loc.statistics
                  const tone = !s ? 'text-warn' : s.evidence.category.startsWith('significant') ? 'text-teal' : s.evidence.category === 'mixed' ? 'text-warn' : 'text-fg'
                  return (
                    <td key={i} className={`px-5 py-3 font-semibold ${tone}`}>
                      {!loc.ok && loc.error ? (
                        <span>
                          {loc.error.error.replace(/_/g, ' ').toLowerCase()}
                          <span className="mt-1 block text-sm font-normal text-fg-muted">{loc.error.message}</span>
                        </span>
                      ) : s ? (
                        s.evidence.label
                      ) : (
                        <span className="font-normal">{loc.analysis_message}</span>
                      )}
                    </td>
                  )
                })}
              </tr>
              {ROWS.map((row) => (
                <tr key={row.label}>
                  <th scope="row" className="px-5 py-2.5 text-left font-normal text-fg-muted">
                    {row.label}
                  </th>
                  {data.locations.map((loc, i) => (
                    <td key={i} className="stat-num px-5 py-2.5 text-fg">
                      {loc.statistics ? row.value(loc.statistics) : '—'}
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th scope="row" className="px-5 py-3 text-left font-normal text-fg-muted">
                  <span className="sr-only">Links</span>
                </th>
                {data.locations.map((loc, i) => (
                  <td key={i} className="px-5 py-3">
                    {loc.ok && (
                      <Link
                        className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline"
                        to={`/results${toSearch({ variable: data.variable_id, latitude: loc.latitude, longitude: loc.longitude, startYear: data.start_year, endYear: data.end_year, place: loc.label })}`}
                      >
                        Full analysis <ArrowUpRight className="size-3.5" aria-hidden />
                      </Link>
                    )}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <SectionHeading title="Annual time series" description="Hover to compare values year by year." />
        <div className="card card-pad">
          <CompareChart result={data} />
        </div>
      </section>

      <section className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:gap-12">
        <div>
          <h2 className="text-xl font-bold">Summary</h2>
          <ul className="measure mt-3 space-y-2 leading-relaxed text-fg-muted">
            {data.summary.lines.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p className="mt-3 text-sm text-fg-subtle">Written by fixed rules from the computed statistics.</p>
        </div>
        <div className="panel self-start p-5">
          <h2 className="font-bold">Read this comparison carefully</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] text-fg-muted marker:text-fg-subtle">
            {data.summary.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}
