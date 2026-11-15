import { ArrowRight, ChevronDown, Globe2, Hexagon, PenSquare, Square, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Rectangle, Tooltip } from 'react-leaflet'
import { useNavigate, useSearchParams } from 'react-router'
import { AnalysisModeSwitch } from '../components/common/AnalysisModeSwitch'
import { InfoTip } from '../components/common/InfoTip'
import { useMapColors } from '../theme/theme'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { TimeRangePanel } from '../components/dashboard/TimeRangePanel'
import { PolygonDrawLayer } from '../components/map/PolygonDrawLayer'
import { RegionMap } from '../components/map/RegionMap'
import { BackgroundJobPanel } from '../components/jobs/BackgroundJobPanel'
import { AreaPreviewCard } from '../components/region/AreaPreviewCard'
import { CountrySearch } from '../components/region/CountrySearch'
import { PolygonPanel } from '../components/region/PolygonPanel'
import { useAreaPreview, useCountries, useDebounced } from '../hooks/useAreas'
import { useRegionalConfig } from '../hooks/useRegional'
import type { BBox, RegionalConfig } from '../types/api'
import type { AreaGeometry, AreaRef } from '../types/area'
import { formatNumber } from '../utils/format'
import { editableVertices, geometryBBox, validateVertices, verticesToGeometry } from '../utils/polygon'
import type { LatLng } from '../utils/polygon'
import { complexityLabel, expectedCells, fromRegionalSearch, shapeOf, sphericalAreaKm2, toRegionalSearch, validateBox } from '../utils/region'
import { validateYears } from '../utils/validation'

type Shape = 'rectangle' | 'country' | 'polygon'

const SHAPES: { id: Shape; label: string; icon: typeof Square }[] = [
  { id: 'rectangle', label: 'Rectangle', icon: Square },
  { id: 'country', label: 'Country', icon: Globe2 },
  { id: 'polygon', label: 'Polygon', icon: Hexagon },
]

/** Small stable number from a string (drives map re-fitting when a new boundary arrives). */
const tokenOf = (s: string) => [...s].reduce((h, c) => (Math.imul(31, h) + c.charCodeAt(0)) | 0, 7) >>> 0

export default function RegionalExplore() {
  const { data, error, loading, retry } = useRegionalConfig()
  return (
    <div className="mx-auto max-w-7xl px-4 pb-10 pt-10 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">Analyse a region or country</h1>
          <p className="measure mt-2 text-fg-muted">An area-weighted trend for a rectangle, a country or your own polygon, plus a per-cell significance map.</p>
        </div>
        <AnalysisModeSwitch />
      </header>
      <div className="mt-8">
        {loading && <LoadingState title="Loading regional analysis settings…" />}
        {error && <ErrorState error={error} title="Could not connect to the Earth Scope backend" onRetry={retry} />}
        {data && <RegionalForm config={data} />}
      </div>
    </div>
  )
}

function NumberField({ id, label, value, onChange, hint }: { id: string; label: string; value: string; onChange: (v: string) => void; hint: string }) {
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      <input id={id} inputMode="decimal" className="input stat-num" value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={`${id}-hint`} />
      <p id={`${id}-hint`} className="mt-1 text-xs text-fg-subtle">{hint}</p>
    </div>
  )
}

function RegionalForm({ config }: { config: RegionalConfig }) {
  const navigate = useNavigate()
  const colors = useMapColors()
  const [search] = useSearchParams()
  const initial = fromRegionalSearch(search)
  const [variable, setVariable] = useState(initial?.variable ?? config.variables[0].id)
  const [fields, setFields] = useState(() => {
    const b = initial?.bbox
    return b
      ? { lat_min: String(b.lat_min), lat_max: String(b.lat_max), lon_min: String(b.lon_min), lon_max: String(b.lon_max) }
      : { lat_min: '', lat_max: '', lon_min: '', lon_max: '' }
  })
  const [drawing, setDrawing] = useState(false)
  const [focusToken, setFocusToken] = useState(initial ? 1 : 0)
  const [start, setStart] = useState(initial?.startYear ?? config.default_start_year)
  const [end, setEnd] = useState(initial?.endYear ?? config.default_end_year)
  const [coverage, setCoverage] = useState(initial?.coverageThreshold ?? config.default_coverage_threshold)
  const [submitted, setSubmitted] = useState(false)

  // --- Country / polygon selection ---
  const [shape, setShape] = useState<Shape>(() => shapeOf(search))
  const [iso3, setIso3] = useState<string | null>(initial?.area?.kind === 'country' ? initial.area.iso3 : null)
  const initialPoly = initial?.area?.kind === 'polygon' ? initial.area.geometry : null
  const [vertices, setVertices] = useState<LatLng[]>(() => (initialPoly ? editableVertices(initialPoly) ?? [] : []))
  const [uploaded, setUploaded] = useState<AreaGeometry | null>(() => (initialPoly && !editableVertices(initialPoly) ? initialPoly : null))
  const [polyDrawing, setPolyDrawing] = useState(false)
  const [polyFocus, setPolyFocus] = useState(0)
  const finishPolygon = () => {
    setPolyDrawing(false)
    setPolyFocus((t) => t + 1) // fly to the finished polygon so its vertices can be edited
  }
  const [polyName, setPolyName] = useState(initial?.area?.kind === 'polygon' ? initial.area.name : 'Custom polygon')
  const countries = useCountries()

  const polyErrors = uploaded ? [] : validateVertices(vertices)
  const polyGeometry: AreaGeometry | null = uploaded ?? (!polyDrawing && vertices.length >= 3 && polyErrors.length === 0 ? verticesToGeometry(vertices) : null)
  const areaRef: AreaRef | null =
    shape === 'country' && iso3 ? { kind: 'country', iso3 } : shape === 'polygon' && polyGeometry ? { kind: 'polygon', geometry: polyGeometry, name: polyName.trim() || 'Custom polygon' } : null
  const previewParams = useMemo(
    () => (areaRef && !yearErrorFor(start, end, config) ? { area: areaRef, variable, startYear: start, endYear: end } : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(areaRef), variable, start, end],
  )
  const preview = useAreaPreview(useDebounced(previewParams, shape === 'polygon' ? 450 : 0))
  const previewData = preview.data ?? (preview.loading ? preview.lastData : null)
  const areaShape = shape === 'country' ? previewData?.area.geometry ?? null : shape === 'polygon' && uploaded ? uploaded : null
  const areaFocus = shape === 'country' && previewData ? tokenOf(previewData.area.geometry_id) : 0

  const empty = Object.values(fields).every((v) => v.trim() === '')
  const box: BBox | null = empty
    ? null
    : { lat_min: Number(fields.lat_min), lat_max: Number(fields.lat_max), lon_min: Number(fields.lon_min), lon_max: Number(fields.lon_max) }
  const boxErrors = validateBox(box, { minSpan: config.min_span_deg, maxSpan: config.max_span_deg })
  const validBox = boxErrors.length === 0 ? box : null
  // Recompute the grid preview only when the box values change (key = the four numbers).
  const boxKey = validBox ? `${validBox.lat_min},${validBox.lat_max},${validBox.lon_min},${validBox.lon_max}` : ''
  const cells = useMemo(() => {
    if (!boxKey) return []
    const [lat_min, lat_max, lon_min, lon_max] = boxKey.split(',').map(Number)
    return expectedCells({ lat_min, lat_max, lon_min, lon_max })
  }, [boxKey])
  const limits = { minYear: config.min_year, maxYear: config.max_year, minSpan: config.min_year_span, defaultEnd: config.default_end_year, minValidMonths: 10 }
  const yearError = validateYears(start, end, limits)
  const selected = config.variables.find((v) => v.id === variable) ?? config.variables[0]

  const setBox = (b: BBox, focus = false) => {
    setFields({ lat_min: String(b.lat_min), lat_max: String(b.lat_max), lon_min: String(b.lon_min), lon_max: String(b.lon_max) })
    if (focus) setFocusToken((t) => t + 1)
  }

  const areaReady = !!(areaRef && preview.data && preview.data.preflight.available && JSON.stringify(previewParams?.area) === JSON.stringify(areaRef))
  const areaProblem =
    shape === 'country'
      ? !iso3 ? 'Search and select a country first.' : preview.data && !preview.data.preflight.available ? 'This country exceeds the instant-analysis limits — run it as a background analysis (panel on the right).' : 'The boundary is still loading.'
      : polyDrawing ? 'Finish the polygon first.' : !polyGeometry ? polyErrors[0] ?? 'Draw a polygon or upload a GeoJSON file first.' : preview.data && !preview.data.preflight.available ? 'This polygon exceeds the instant-analysis limits — run it as a background analysis (panel on the right).' : 'The polygon is still being checked.'
  const jobParams = useMemo(
    () =>
      areaRef && !yearError && preview.data && JSON.stringify(previewParams?.area) === JSON.stringify(areaRef)
        ? { area: areaRef, variable, startYear: start, endYear: end, coverageThreshold: coverage }
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(areaRef), preview.data, variable, start, end, coverage, yearError],
  )

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (yearError) return
    const common = { variable, startYear: start, endYear: end, coverageThreshold: coverage}
    if (shape === 'rectangle') {
      if (!validBox) return
      navigate(`/regional/results${toRegionalSearch({ ...common, bbox: validBox })}`)
      return
    }
    if (!areaReady || !areaRef || !preview.data) return
    navigate(`/regional/results${toRegionalSearch({ ...common, bbox: preview.data.area.bbox, area: areaRef })}`)
  }

  return (
    <form onSubmit={onSubmit} noValidate>
      <div role="tablist" aria-label="Area type" className="seg">
        {SHAPES.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={shape === id}
            onClick={() => {
              setShape(id)
              setDrawing(false)
              setPolyDrawing(false)
            }}
            className="seg-item px-4"
          >
            <Icon className="size-4" aria-hidden /> {label}
          </button>
        ))}
      </div>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-10">
        {/* MAP + PREVIEW: the visual anchor */}
        <div className="min-w-0 space-y-5 lg:sticky lg:top-20 lg:self-start">
          <RegionMap
            box={
              shape === 'rectangle'
                ? box && boxErrors.every((e) => !e.startsWith('All four')) ? box : null
                : shape === 'polygon' && polyGeometry ? geometryBBox(polyGeometry) : null
            }
            showBox={shape === 'rectangle'}
            onChange={shape === 'rectangle' ? (b) => setBox(b) : undefined}
            drawing={shape === 'rectangle' && drawing}
            onDrawingDone={() => {
              setDrawing(false)
              setFocusToken((t) => t + 1) // zoom to the new region so it can be inspected and edited
            }}
            focusToken={shape === 'rectangle' ? focusToken : shape === 'country' ? areaFocus : polyFocus}
            editable={shape === 'rectangle'}
            shape={areaShape}
            className="h-[22rem] sm:h-[32rem]"
          >
            {shape === 'polygon' && !uploaded && (
              <PolygonDrawLayer
                vertices={vertices}
                onChange={setVertices}
                drawing={polyDrawing}
                onFinish={finishPolygon}
                invalid={!polyDrawing && polyErrors.length > 0}
              />
            )}
            {shape === 'rectangle' && cells.length <= 400 &&
              cells.map((c) => (
                <Rectangle
                  key={`${c.lat},${c.lon}`}
                  bounds={c.bounds}
                  pathOptions={{ color: colors.subtle, weight: 0.6, dashArray: c.partial ? '3 3' : undefined, fillColor: colors.accent, fillOpacity: c.partial ? 0.04 : 0.1 }}
                >
                  <Tooltip sticky>
                    Grid cell {c.lat}°, {c.lon}°{c.partial ? ' — partly inside (weighted by overlap area)' : ''}
                  </Tooltip>
                </Rectangle>
              ))}
          </RegionMap>
          {shape === 'rectangle' ? (
            <RegionPreview box={validBox} cells={cells.length} />
          ) : (
            <AreaPreviewCard
              data={areaRef ? previewData : null}
              loading={preview.loading}
              error={areaRef ? preview.error : null}
              onRetry={preview.retry}
              emptyText={
                shape === 'country'
                  ? 'Select a country to see its boundary, area, NASA grid cells and request count.'
                  : 'Draw or upload a polygon to see its area, NASA grid cells and request count.'
              }
            />
          )}
          {shape !== 'rectangle' && (
            <BackgroundJobPanel
              params={jobParams}
              disabledReason={jobParams ? null : yearError ? 'Fix the time period first.' : `Select ${shape === 'country' ? 'a country' : 'a polygon'} and wait for its check to finish.`}
            />
          )}
        </div>

        {/* CONTROLS */}
        <div className="min-w-0 space-y-7">
          <section aria-labelledby="rg-region">
            <h2 id="rg-region" className="mb-3 text-lg font-bold">
              {shape === 'country' ? 'Country' : shape === 'polygon' ? 'Polygon' : 'Rectangle'}
            </h2>
            {shape === 'country' &&
              (countries.error ? (
                <ErrorState error={countries.error} title="Could not load the country list" onRetry={countries.retry} />
              ) : countries.data ? (
                <CountrySearch countries={countries.data.countries} selected={iso3} onSelect={setIso3} />
              ) : (
                <p className="text-sm text-fg-muted" role="status">
                  Loading countries…
                </p>
              ))}
            {shape === 'polygon' && (
              <PolygonPanel
                vertices={vertices}
                onVertices={setVertices}
                drawing={polyDrawing}
                onDrawing={setPolyDrawing}
                uploaded={uploaded}
                onUploaded={setUploaded}
                name={polyName}
                onName={setPolyName}
                errors={polyErrors}
                onFinish={() => {
                  if (vertices.length >= 3) finishPolygon()
                }}
              />
            )}
            {shape === 'rectangle' && (
              <>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={drawing ? 'btn-primary' : 'btn-secondary'} onClick={() => setDrawing((d) => !d)} aria-pressed={drawing}>
                    {drawing ? <X className="size-4" aria-hidden /> : <PenSquare className="size-4" aria-hidden />}
                    {drawing ? 'Cancel drawing' : box ? 'Draw again' : 'Draw on the map'}
                  </button>
                  {box && (
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => {
                        setFields({ lat_min: '', lat_max: '', lon_min: '', lon_max: '' })
                        setDrawing(false)
                      }}
                    >
                      <Trash2 className="size-4" aria-hidden /> Clear
                    </button>
                  )}
                </div>
                {drawing && (
                  <p className="mt-2 text-sm text-accent" role="status">
                    Drag on the map, or click one corner and then the opposite one.
                  </p>
                )}
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <NumberField id="lat-min" label="South" value={fields.lat_min} onChange={(v) => setFields((f) => ({ ...f, lat_min: v }))} hint="min latitude" />
                  <NumberField id="lat-max" label="North" value={fields.lat_max} onChange={(v) => setFields((f) => ({ ...f, lat_max: v }))} hint="max latitude" />
                  <NumberField id="lon-min" label="West" value={fields.lon_min} onChange={(v) => setFields((f) => ({ ...f, lon_min: v }))} hint="min longitude" />
                  <NumberField id="lon-max" label="East" value={fields.lon_max} onChange={(v) => setFields((f) => ({ ...f, lon_max: v }))} hint="max longitude" />
                </div>
                {box && boxErrors.length > 0 && (
                  <ul className="mt-3 space-y-1 text-sm text-danger" role="alert">
                    {boxErrors.map((er) => (
                      <li key={er}>{er}</li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-sm text-fg-subtle">
                  Each side {config.min_span_deg}°–{config.max_span_deg}°
                  <InfoTip
                    label="rectangle size limits"
                    text={`NASA POWER regional requests must span ${config.nasa_min_span_deg}°–${config.nasa_max_span_deg}° per side. Earth Scope adds half a grid cell on each side to capture cells cut by the edge. For larger areas, use Country or Polygon.`}
                  />
                </p>
                <label htmlFor="preset" className="label mt-4">
                  Or start from an example
                </label>
                <select
                  id="preset"
                  className="input"
                  value=""
                  onChange={(e) => {
                    const p = config.presets.find((x) => x.name === e.target.value)
                    if (p) setBox(p.bbox, true)
                  }}
                >
                  <option value="">Choose an example region…</option>
                  {config.presets.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name} — {p.description}
                    </option>
                  ))}
                </select>
              </>
            )}
          </section>

          <section aria-labelledby="rg-var" className="border-t border-line pt-6">
            <h2 id="rg-var" className="mb-3 text-lg font-bold">
              Variable
            </h2>
            <div role="radiogroup" aria-label="Variable" className="grid gap-1.5">
              {config.variables.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  role="radio"
                  aria-checked={v.id === variable}
                  onClick={() => setVariable(v.id)}
                  className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    v.id === variable ? 'border-accent bg-accent/[0.07] text-fg ring-1 ring-accent' : 'border-line-strong text-fg-muted hover:border-fg-subtle hover:text-fg'
                  }`}
                >
                  <span className="font-semibold">{v.name}</span>
                  <span className="stat-num text-xs text-fg-subtle" title={v.unit_display}>
                    {v.parameter}
                  </span>
                </button>
              ))}
            </div>
            {selected.land_only && <p className="mt-2 text-sm text-fg-muted">Averaged over ice-free land cells only; water and ice cells are excluded.</p>}
          </section>

          <section aria-labelledby="rg-time" className="border-t border-line pt-6">
            <h2 id="rg-time" className="mb-3 text-lg font-bold">
              Period
            </h2>
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
          </section>

          <details className="disclosure border-t border-line pt-5">
            <summary>
              <ChevronDown className="size-4 transition-transform [details[open]_&]:rotate-180" aria-hidden /> Advanced
            </summary>
            <div className="mt-4 space-y-4">
              <div>
                <label htmlFor="coverage" className="label">
                  Minimum spatial coverage per month
                </label>
                <select id="coverage" className="input" value={coverage} onChange={(e) => setCoverage(Number(e.target.value))}>
                  {[0.5, 0.7, 0.8, 0.9, 1].map((v) => (
                    <option key={v} value={v}>
                      {Math.round(v * 100)}% of the area{v === config.default_coverage_threshold ? ' (default)' : ''}
                    </option>
                  ))}
                </select>
                <p className="mt-1.5 text-sm text-fg-subtle">
                  Each cell is weighted by its true area inside the {shape === 'country' ? 'boundary' : shape === 'polygon' ? 'polygon' : 'rectangle'}. Months
                  whose valid cells cover less are excluded, never filled.
                </p>
              </div>
            </div>
          </details>

          <div className="border-t border-line pt-6">
            {submitted && shape === 'rectangle' && (!validBox || yearError) && (
              <div className="mb-3">
                <Notice tone="warn">{!validBox ? boxErrors[0] : yearError}</Notice>
              </div>
            )}
            {submitted && shape !== 'rectangle' && (yearError || !areaReady) && (
              <div className="mb-3">
                <Notice tone="warn">{yearError || areaProblem}</Notice>
              </div>
            )}
            <button type="submit" className="btn-primary w-full text-base">
              {shape === 'country' ? 'Analyse country' : shape === 'polygon' ? 'Analyse polygon' : 'Analyse region'} <ArrowRight className="size-4" aria-hidden />
            </button>
            {shape !== 'rectangle' && <p className="mt-2 text-sm text-fg-subtle">Too large for an instant analysis? Use the background option under the map.</p>}
          </div>
        </div>
      </div>
    </form>
  )
}

function yearErrorFor(start: number, end: number, config: RegionalConfig): string | null {
  return validateYears(start, end, { minYear: config.min_year, maxYear: config.max_year, minSpan: config.min_year_span })
}

function RegionPreview({ box, cells }: { box: BBox | null; cells: number }) {
  if (!box)
    return <p className="text-sm text-fg-subtle">Draw a rectangle, type its edges or pick an example to see its size and NASA grid cells.</p>
  const c = complexityLabel(cells)
  const items: [string, string][] = [
    ['Latitude', `${box.lat_min}° to ${box.lat_max}°`],
    ['Longitude', `${box.lon_min}° to ${box.lon_max}°`],
    ['Size', `${(box.lat_max - box.lat_min).toFixed(2)}° × ${(box.lon_max - box.lon_min).toFixed(2)}°`],
    ['Area', `${formatNumber(Math.round(sphericalAreaKm2(box)), 6)} km²`],
    ['NASA grid cells', `${cells}`],
  ]
  return (
    <div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        {items.map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-sm text-fg-subtle">{k}</dt>
            <dd className="stat-num break-words text-[0.9375rem] text-fg">{v}</dd>
          </div>
        ))}
      </dl>
      <p className={`mt-3 text-sm ${c.tone === 'warn' ? 'text-warn' : 'text-fg-muted'}`}>
        {c.label}. Dashed cells are partly inside and weighted by their area inside the rectangle — not a country or administrative boundary.
      </p>
    </div>
  )
}
