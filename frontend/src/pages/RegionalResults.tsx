import { ArrowLeft, ArrowRightLeft, ChevronDown, Database, Download, ExternalLink, FileJson, FileSpreadsheet, Pencil } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Polygon as LeafletPolygon, Popup, Rectangle } from 'react-leaflet'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AdvancedStatisticsPanel } from '../components/analysis/AdvancedStatisticsPanel'
import { DataTable } from '../components/analysis/DataTable'
import { InterpretationPanel } from '../components/analysis/InterpretationPanel'
import { KeyResultCards } from '../components/analysis/KeyResultCards'
import { StatisticsPanel } from '../components/analysis/StatisticsPanel'
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { DataModeBadge } from '../components/common/DataModeBadge'
import { Disclosure } from '../components/common/Disclosure'
import { useMapColors } from '../theme/theme'
import { SectionHeading } from '../components/common/SectionHeading'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { RegionMap } from '../components/map/RegionMap'
import { SpatialTrendExplorer } from '../components/spatial/SpatialTrendExplorer'
import { useRegionalAnalysis } from '../hooks/useRegional'
import type { GridCellInfo, RegionalAnalysisResponse, RegionalParams } from '../types/api'
import { formatDateTime, formatNumber, formatSigned } from '../utils/format'
import { leafletPositions, needsUnwrap, shiftLon } from '../utils/polygon'
import { useAiPageContext } from '../context/aiChatContext'
import { regionalContext } from '../utils/buildAiContext'
import { fromRegionalSearch, shapeOf, toRegionalSearch } from '../utils/region'
import {
  downloadRegionalAnnual,
  downloadRegionalCells,
  downloadRegionalMetadata,
  downloadRegionalMonthly,
  downloadRegionalStatistics,
} from '../utils/regionalExport'

const SECTIONS = [
  ['finding', 'Finding'],
  ['chart', 'Time series'],
  ['map', 'Grid cells'],
  ['spatial', 'Spatial trends'],
  ['interpretation', 'Interpretation'],
  ['statistics', 'Statistics'],
  ['data', 'Data & source'],
] as const

// Single-hue sequential ramp (dark = low, bright = high) for cell values.
const RAMP_LO = [18, 52, 77]
const RAMP_HI = [125, 232, 249]
function rampColor(t: number): string {
  const c = RAMP_LO.map((lo, i) => Math.round(lo + (RAMP_HI[i] - lo) * Math.max(0, Math.min(1, t))))
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

export default function RegionalResults() {
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const params = useMemo(() => fromRegionalSearch(search), [search])
  const { data, error, loading, retry } = useRegionalAnalysis(params)
  useAiPageContext(
    params && data
      ? regionalContext(
          params,
          `${data.metadata.variable_name} for ${data.metadata.area_name ?? 'the selected rectangle'}, ${data.metadata.start_year}–${data.metadata.end_year}`,
        )
      : null,
  )

  if (!params) {
    return (
      <Page>
        <Notice tone="warn">
          {search.get('job') !== null
            ? 'This background-job link is not valid. '
            : shapeOf(search) === 'polygon'
            ? 'The custom polygon for this link is no longer available in this browser (large polygons are kept only for the current session). Earth Scope will not substitute a rectangle — please draw or upload it again. '
            : shapeOf(search) === 'country'
              ? 'The country code in this link is missing or invalid. '
              : 'No region was provided. '}
          <Link to={`/regional${shapeOf(search) !== 'rectangle' ? `?shape=${shapeOf(search)}` : ''}`} className="text-accent underline">Set up a regional analysis</Link>.
        </Notice>
      </Page>
    )
  }
  const editLink = params.jobId ? `/jobs/${params.jobId}` : `/regional${toRegionalSearch(params)}`

  return (
    <Page>
      <Link to={editLink} className="btn-ghost -ml-3 mb-6">
        <ArrowLeft className="size-4" aria-hidden /> {params.jobId ? 'Job details' : 'Edit region'}
      </Link>

      {loading && (
        <LoadingState
          title={
            params.jobId
              ? 'Loading the stored background-job result…'
              : params.area
                ? `Retrieving NASA POWER tiles for the ${params.area.kind === 'country' ? 'country' : 'polygon'}…`
                : 'Retrieving NASA POWER regional grid…'
          }
          steps={
            params.jobId
              ? ['The analysis already ran in a background worker; its verified result files are being read.']
              : params.area
              ? [
                  '1. Intersecting the boundary with the NASA grid (exact overlap areas)',
                  '2. Requesting the regional tiles from NASA POWER (a few at a time, with retries)',
                  '3. Merging tiles (each cell once), polygon-weighted monthly and annual means',
                  '4. Running the trend tests',
                ]
              : [
                  '1. Requesting every grid cell in the region from NASA POWER',
                  '2. Removing fill values and computing area-weighted monthly means',
                  '3. Aggregating to annual values and running the trend tests',
                ]
          }
        />
      )}

      {error && (
        <ErrorState error={error} title="The regional analysis could not be completed" onRetry={error.retryable ? retry : undefined}>
          <Link to={editLink} className="btn-secondary">
            <Pencil className="size-4" aria-hidden /> {params.jobId ? 'Job details' : 'Edit region'}
          </Link>
          {!params.jobId && error.suggestedVariables.map((id) => (
            <button key={id} type="button" className="btn-secondary" onClick={() => navigate(`/regional/results${toRegionalSearch({ ...params, variable: id })}`)}>
              <ArrowRightLeft className="size-4" aria-hidden /> Analyse {id.replace(/_/g, ' ')} here instead
            </button>
          ))}
        </ErrorState>
      )}

      {data && <Dashboard data={data} params={params} />}
    </Page>
  )
}

function Dashboard({ data, params }: { data: RegionalAnalysisResponse; params: RegionalParams }) {
  const m = data.metadata
  const b = m.bbox
  const s = data.statistics
  const isArea = m.area_mode === 'country' || m.area_mode === 'polygon'
  return (
    <div>
      <header className="border-b border-line pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">
              {m.variable_name} · {isArea ? `${m.area_name}${m.iso3 ? ` (${m.iso3})` : ''}` : `${b.lat_min}° to ${b.lat_max}°, ${b.lon_min}° to ${b.lon_max}°`}
            </h1>
            <p className="measure mt-2 text-fg-muted">
              <span className="stat-num">
                {m.start_year}–{m.end_year}
              </span>{' '}
              · {isArea ? 'polygon' : 'area'}-weighted mean of {m.n_cells_used} NASA grid cells
              {' '}·{' '}
              {m.area_mode === 'country'
                ? `${m.boundary?.source ?? 'boundary dataset'} boundary (${m.boundary?.version ?? ''}); another dataset may differ slightly`
                : m.area_mode === 'polygon'
                  ? 'your polygon, not an administrative boundary'
                  : 'a rectangle, not a country or administrative boundary'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {m.execution_mode === 'background' && (
              <span className="chip" title={`Background job ${m.job_id ?? ''}`}>
                Background job result
              </span>
            )}
            <DataModeBadge mode={m.data_mode} size="lg" />
          </div>
        </div>
        <nav aria-label="Result sections" className="mt-5 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="text-fg-muted hover:text-accent">
              {label}
            </a>
          ))}
        </nav>
      </header>

      <div className="mt-8 space-y-14">
        {data.warnings.length > 0 && (
          <div className="space-y-2">
            {data.warnings.map((w) => (
              <Notice key={w} tone="warn">
                {w}
              </Notice>
            ))}
          </div>
        )}

        <section id="finding" className="scroll-mt-24" aria-label="Finding">
          {s ? (
            <>
              <KeyResultCards stats={s} rateUnit={m.rate_unit} />
              <RegionalFacts data={data} />
            </>
          ) : (
            <Notice tone="warn">{data.analysis_message ?? 'Statistics are unavailable for this region.'}</Notice>
          )}
        </section>

        <section id="chart" className="scroll-mt-24">
          <SectionHeading title="Regional time series" description="The shaded band is variability across cells, not trend uncertainty." />
          <div className="card card-pad">
            <TimeSeriesChart result={data} />
          </div>
        </section>

        <section id="map" className="scroll-mt-24">
          <SectionHeading
            title={isArea ? 'Grid cells inside the boundary' : 'Grid cells in the region'}
            description="Each cell is a NASA POWER grid cell, weighted by its area inside the selection. Click one for details."
          />
          <CellMap data={data} />
        </section>

        <section id="spatial" className="scroll-mt-24">
          <SectionHeading
            title="Spatial Trend Explorer"
            description="Every cell's own trend, so local changes hidden by the average become visible. Significance is corrected for the number of cells tested."
          />
          <SpatialTrendExplorer params={params} />
        </section>

        <section id="interpretation" className="scroll-mt-24">
          <SectionHeading title="What this means" />
          <InterpretationPanel interpretation={data.interpretation} />
        </section>

        {s && (
          <section id="statistics" className="scroll-mt-24">
            <SectionHeading
              title="Statistics"
              description={`Earth Scope's methods on the regional annual series (${s.n_years} years, ${s.first_year}–${s.last_year}), α = ${s.alpha}.`}
            />
            <StatisticsPanel stats={s} rateUnit={m.rate_unit} />
            {s.advanced && (
              <Disclosure title="Advanced statistics" summary="Do consecutive years depend on each other, and does accounting for that change the conclusion?">
                <AdvancedStatisticsPanel stats={s} rateUnit={m.rate_unit} interpretation={data.interpretation} />
              </Disclosure>
            )}
          </section>
        )}

        <section id="data" className="scroll-mt-24">
          <SectionHeading title="Data & source" />
          <Overview data={data} />
          <div className="mt-6 space-y-3">
            <Disclosure title={`Regional monthly series (${data.monthly.length})`} summary="Every month, including months excluded for low coverage." flush>
              <DataTable result={data} />
            </Disclosure>
            <Provenance data={data} />
          </div>
          <div className="mt-8">
            <h3 className="mb-3 font-bold">Export</h3>
            <Exports data={data} />
          </div>
        </section>
      </div>
    </div>
  )
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-sm text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 break-words text-[0.9375rem] text-fg">{value}</dd>
    </div>
  )
}

function Overview({ data }: { data: RegionalAnalysisResponse }) {
  const m = data.metadata
  const b = m.bbox
  const isArea = m.area_mode === 'country' || m.area_mode === 'polygon'
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-4 min-[420px]:grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
      {isArea && <Item label="Analysis mode" value={m.area_mode === 'country' ? 'Country boundary' : 'Custom polygon'} />}
      {isArea && <Item label={m.area_mode === 'country' ? 'Country' : 'Polygon'} value={`${m.area_name}${m.iso3 ? ` · ISO ${m.iso3}` : ''}`} />}
      {m.boundary && <Item label="Boundary source" value={`${m.boundary.source} · ${m.boundary.version}`} />}
      {m.boundary && <Item label="Boundary licence" value={m.boundary.license ?? '—'} />}
      <Item label="Variable" value={`${m.variable_name} (${m.parameter})`} />
      <Item label="Bounding box" value={`${b.lat_min.toFixed(2)}° to ${b.lat_max.toFixed(2)}° lat · ${b.lon_min.toFixed(2)}° to ${b.lon_max.toFixed(2)}° lon`} />
      <Item label={isArea ? 'Area (equal-area)' : 'Area (spherical)'} value={`${formatNumber(Math.round(m.region_area_km2), 7)} km²`} />
      {m.geodesic_area_km2 != null && <Item label="Geodesic area (WGS84)" value={`${formatNumber(Math.round(m.geodesic_area_km2), 7)} km²`} />}
      {isArea && <Item label="Geometry" value={`${m.n_components} part(s) · ${m.n_vertices?.toLocaleString()} vertices · ${m.geometry_id}`} />}
      {isArea && <Item label="NASA requests" value={`${m.n_tiles} tile(s); ${m.n_duplicates} duplicate cell(s) merged`} />}
      {m.grid_representability != null && <Item label="Grid representability" value={`${(m.grid_representability * 100).toFixed(3)}% of the area covered by intersecting cells`} />}
      <Item label="Grid cells used" value={`${m.n_cells_used}${m.n_cells_excluded ? ` (+${m.n_cells_excluded} excluded)` : ''}`} />
      <Item label="Mean spatial coverage" value={`${(data.summary.mean_coverage * 100).toFixed(1)}%${m.land_fraction !== null ? ` of land (${(m.land_fraction * 100).toFixed(0)}% of box is land)` : ''}`} />
      <Item label="Data source" value={`NASA POWER · ${m.sources.join(', ')}`} />
      <Item label="Period" value={`${m.start_year} – ${m.end_year} · monthly`} />
      <Item label="Aggregation" value="Area-weighted mean (exact spherical overlap areas)" />
    </dl>
  )
}

const STATUS_TEXT: Record<GridCellInfo['status'], string> = {
  valid: 'Complete record',
  partial: 'Some months missing',
  missing: 'No valid data',
  excluded: 'Excluded (water or ice for a land-only variable)',
}

function CellMap({ data }: { data: RegionalAnalysisResponse }) {
  const colors = useMapColors()
  const [yearIdx, setYearIdx] = useState(-1) // -1 = period mean
  const m = data.metadata
  const valueOf = (c: GridCellInfo) => (yearIdx < 0 ? c.period_mean : c.annual[yearIdx])
  const vals = data.cells.filter((c) => c.status !== 'excluded').map(valueOf).filter((v): v is number => v !== null)
  const lo = vals.length ? Math.min(...vals) : 0
  const hi = vals.length ? Math.max(...vals) : 1
  const span = hi - lo || 1
  const unwrap = m.geometry ? needsUnwrap(m.geometry) : false
  return (
    <div className="card card-pad">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <label htmlFor="cell-year" className="text-sm text-fg-muted">
          Colour cells by
        </label>
        <select id="cell-year" className="input w-auto py-1.5" value={yearIdx} onChange={(e) => setYearIdx(Number(e.target.value))}>
          <option value={-1}>Period mean ({m.start_year}–{m.end_year})</option>
          {data.cell_years.map((y, i) => (
            <option key={y} value={i}>
              {y} annual mean
            </option>
          ))}
        </select>
      </div>
      <RegionMap box={m.bbox} focusToken={1} shape={m.geometry ?? null} showBox={!m.geometry} className="h-[22rem] sm:h-[28rem]">
        {data.cells.map((c) => {
          const v = valueOf(c)
          const excluded = c.status === 'excluded'
          const fill = v === null || excluded ? colors.surface : rampColor((v - lo) / span)
          const pathOptions = {
            color: excluded ? colors.subtle : c.status === 'missing' ? colors.warn : colors.ground,
            weight: excluded || c.status === 'missing' ? 1.2 : 0.5,
            dashArray: excluded ? '2 3' : c.overlap_fraction < 0.999 ? '4 3' : undefined,
            fillColor: fill,
            fillOpacity: excluded ? 0.25 : v === null ? 0.1 : 0.75,
          }
          const popup = (
            <Popup>
              <div className="space-y-0.5 text-xs">
                <p className="font-semibold">
                  Grid cell {c.latitude}°, {c.longitude}°
                </p>
                <p>Cell: {c.lat_min}° to {c.lat_max}° lat, {c.lon_min}° to {c.lon_max}° lon</p>
                <p>{m.variable_name} ({m.parameter}), {yearIdx < 0 ? 'period mean' : `${data.cell_years[yearIdx]} mean`}: {v === null ? 'no valid value' : `${formatNumber(v, 4)} ${m.unit_display}`}</p>
                <p>Availability: {c.valid_months}/{c.total_months} months · {STATUS_TEXT[c.status]}</p>
                <p>Inside {m.area_mode === 'country' ? 'the country' : m.area_mode === 'polygon' ? 'the polygon' : 'the region'}: {(c.overlap_fraction * 100).toFixed(0)}% of the cell ({formatNumber(c.overlap_area_km2, 4)} km²) · weight {(c.weight * 100).toFixed(2)}%</p>
                <p>Source: NASA POWER ({m.sources.join(', ')})</p>
              </div>
            </Popup>
          )
          const key = `${c.latitude},${c.longitude}`
          return c.clip ? (
            <LeafletPolygon key={key} positions={leafletPositions(c.clip, unwrap)} pathOptions={pathOptions}>{popup}</LeafletPolygon>
          ) : (
            <Rectangle key={key} bounds={[[c.lat_min, shiftLon(c.lon_min, unwrap)], [c.lat_max, shiftLon(c.lon_max, unwrap)]]} pathOptions={pathOptions}>{popup}</Rectangle>
          )
        })}
      </RegionMap>
      <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-fg-muted">
        <span className="flex items-center gap-2">
          <span className="stat-num">{formatNumber(lo, 4)}</span>
          <span className="inline-block h-2.5 w-28 rounded" style={{ background: `linear-gradient(to right, ${rampColor(0)}, ${rampColor(1)})` }} />
          <span className="stat-num">{formatNumber(hi, 4)}</span> {m.unit_display}
        </span>
        <span className="flex items-center gap-1.5"><span className="inline-block size-3 border border-dashed border-fg-subtle" /> Partly inside (weighted by overlap)</span>
        <span className="flex items-center gap-1.5"><span className="inline-block size-3 border-2 border-warn" /> No valid data</span>
        <span className="flex items-center gap-1.5"><span className="inline-block size-3 border border-dotted border-fg-subtle bg-line" /> Excluded</span>
      </div>
      <p className="mt-2 text-sm text-fg-subtle">
        Cells near the poles cover less area than cells near the equator; each cell’s weight is its true area inside the{' '}
        {m.area_mode === 'country' ? 'country boundary' : m.area_mode === 'polygon' ? 'polygon' : 'rectangle'}, not an equal share.
        {m.geometry ? ' Cells cut by the boundary are drawn clipped to it; the outline is the selected boundary.' : ''}
      </p>
    </div>
  )
}

/** Secondary facts under the headline finding: robust slope, data completeness, spatial coverage. */
function RegionalFacts({ data }: { data: RegionalAnalysisResponse }) {
  const s = data.statistics!
  const m = data.metadata
  const robust = s.advanced?.robust_evidence
  const facts: [string, string, string][] = [
    [
      'Sen’s slope',
      `${formatSigned(s.sens_slope.slope)} ${m.rate_unit}`,
      s.sens_slope.ci_lower !== null ? `95% CI ${formatSigned(s.sens_slope.ci_lower)} to ${formatSigned(s.sens_slope.ci_upper)}` : '—',
    ],
    ['OLS 95% CI', `${formatSigned(s.regression.ci_lower)} to ${formatSigned(s.regression.ci_upper)}`, m.rate_unit],
    ['Valid months', `${data.summary.n_monthly_valid} / ${data.summary.n_monthly_total}`, `${data.summary.n_annual_used} of ${data.summary.n_annual_total} years used`],
    [
      'Spatial coverage',
      `${(data.summary.mean_coverage * 100).toFixed(1)}%`,
      `${m.n_cells_used} cells${m.n_cells_excluded ? `, ${m.n_cells_excluded} excluded` : ''}; months under ${Math.round(m.coverage_threshold * 100)}% dropped`,
    ],
  ]
  return (
    <div className="mt-4">
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 px-1 min-[480px]:grid-cols-2 lg:grid-cols-4">
        {facts.map(([k, v, d]) => (
          <div key={k} className="min-w-0">
            <dt className="text-sm text-fg-subtle">{k}</dt>
            <dd className="stat-num text-[0.9375rem] text-fg">{v}</dd>
            <dd className="text-xs text-fg-subtle">{d}</dd>
          </div>
        ))}
      </dl>
      {robust && <p className="mt-3 px-1 text-sm text-fg-muted">Autocorrelation-aware evidence: {robust.label}</p>}
    </div>
  )
}

function Provenance({ data }: { data: RegionalAnalysisResponse }) {
  const m = data.metadata
  const r = m.request_bbox
  return (
    <details className="group rounded-xl border border-line text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <Database className="size-4 shrink-0 text-fg-subtle" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-base font-semibold text-fg">Data source, method &amp; NASA requests</span>
          <span className="block truncate text-fg-subtle">
            NASA POWER · {m.parameter} · {m.request_manifest ? `${m.n_tiles} tile request(s)` : '1 regional request'} · retrieved {formatDateTime(m.retrieved_at)}
          </span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-line px-5 pb-5 pt-4">
      <dl className="grid gap-3 text-fg-muted sm:grid-cols-2">
        <div><dt className="text-sm text-fg-subtle">Provider</dt><dd>{m.provider}</dd></div>
        <div><dt className="text-sm text-fg-subtle">Dataset</dt><dd>{m.dataset_title ?? '—'}{m.api_version ? ` (API ${m.api_version})` : ''}</dd></div>
        <div><dt className="text-sm text-fg-subtle">Grid</dt><dd>{m.grid_resolution}; {m.n_cells_returned} cells returned, {m.n_cells_used} used{m.n_duplicates ? `, ${m.n_duplicates} duplicates ignored` : ''}</dd></div>
        <div>
          <dt className="text-sm text-fg-subtle">{m.request_manifest ? `Extent of the ${m.n_tiles} NASA tile(s)` : 'Request box (expanded by half a cell)'}</dt>
          <dd className="font-mono text-xs">{r.lat_min} to {r.lat_max} lat, {r.lon_min} to {r.lon_max} lon</dd>
        </div>
        {m.boundary && (
          <div className="sm:col-span-2">
            <dt className="text-sm text-fg-subtle">Boundary</dt>
            <dd>
              {m.boundary.dataset} · {m.boundary.version} · id {m.boundary.boundary_id}
              {m.boundary.year_represented ? ` · year represented ${m.boundary.year_represented}` : ''} · licence {m.boundary.license ?? '—'}
              {m.boundary.upstream_source ? ` · upstream ${m.boundary.upstream_source}` : ''}
              <span className="block text-xs text-fg-subtle">{m.boundary.attribution}</span>
            </dd>
          </div>
        )}
        {m.geometry_id && (
          <div className="sm:col-span-2">
            <dt className="text-sm text-fg-subtle">Geometry used for the calculation</dt>
            <dd>
              {m.geometry_id} · {m.n_components} part(s), {m.n_vertices?.toLocaleString()} vertices · WGS84 lon/lat; overlap areas on an equal-area projection
              {(m.geometry_notes ?? []).map((n) => <span key={n} className="block text-xs text-fg-subtle">{n}</span>)}
            </dd>
          </div>
        )}
        <div className="sm:col-span-2"><dt className="text-sm text-fg-subtle">Aggregation</dt><dd>{m.aggregation_method}</dd></div>
        <div className="sm:col-span-2"><dt className="text-sm text-fg-subtle">Partial cells</dt><dd>{m.partial_cell_rule}</dd></div>
        <div><dt className="text-sm text-fg-subtle">Units (as reported)</dt><dd>{m.units_raw ?? 'not reported'} · missing-value code {m.fill_value}</dd></div>
        <div><dt className="text-sm text-fg-subtle">Retrieved</dt><dd>{formatDateTime(m.retrieved_at)}{m.served_from_cache ? ' (from cache)' : ''}</dd></div>
      </dl>
      <div className="mt-3 flex flex-wrap gap-4">
        <a className="inline-flex items-center gap-1 text-accent hover:underline" href={m.documentation_url} target="_blank" rel="noreferrer">Monthly API docs <ExternalLink className="size-3" aria-hidden /></a>
        <a className="inline-flex items-center gap-1 text-accent hover:underline" href={m.parameter_docs_url} target="_blank" rel="noreferrer">Parameter definitions <ExternalLink className="size-3" aria-hidden /></a>
      </div>
      {m.request_url && (
        <details className="mt-3">
          <summary className="cursor-pointer text-fg-muted hover:text-fg">Show the exact NASA POWER regional request</summary>
          <a href={m.request_url} target="_blank" rel="noreferrer" className="mt-2 block break-all rounded-lg bg-sunken p-3 font-mono text-xs text-accent">{m.request_url}</a>
        </details>
      )}
      {m.request_manifest && m.request_manifest.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-fg-muted hover:text-fg">
            Show all {m.request_manifest.length} NASA POWER requests (tile manifest)
          </summary>
          <ol className="mt-2 space-y-2">
            {m.request_manifest.map((t) => (
              <li key={t.tile} className="rounded-lg bg-sunken p-2 text-xs">
                <span className="font-semibold text-fg">{t.tile}</span> · lat {t.lat_min}…{t.lat_max}, lon {t.lon_min}…{t.lon_max} · {t.cells_returned} cells returned, {t.cells_used} used ·{' '}
                {t.attempts} attempt(s){t.from_cache ? ' · cached' : ''}
                {t.url && (
                  <a href={t.url} target="_blank" rel="noreferrer" className="mt-1 block break-all font-mono text-accent">{t.url}</a>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
      </div>
    </details>
  )
}

function Exports({ data }: { data: RegionalAnalysisResponse }) {
  const items = [
    { label: 'Monthly regional series', sub: `CSV · ${data.monthly.length} rows`, icon: FileSpreadsheet, fn: downloadRegionalMonthly },
    { label: 'Annual regional series', sub: `CSV · ${data.annual.length} rows`, icon: FileSpreadsheet, fn: downloadRegionalAnnual },
    { label: 'Statistical summary', sub: 'JSON · all test results', icon: FileJson, fn: downloadRegionalStatistics },
    { label: 'Grid-cell metadata', sub: `CSV · ${data.cells.length} cells`, icon: FileSpreadsheet, fn: downloadRegionalCells },
    { label: 'Complete analysis metadata', sub: 'JSON · provenance + cells', icon: FileJson, fn: downloadRegionalMetadata },
  ]
  return (
    <div>
      <div className="flex flex-wrap gap-3">
        {items.map(({ label, sub, fn }) => (
          <button key={label} type="button" className="btn-secondary" onClick={() => fn(data)}>
            <Download className="size-4 text-fg-subtle" aria-hidden />
            {label}
            <span className="font-normal text-fg-subtle">{sub}</span>
          </button>
        ))}
      </div>
      <p className="mt-3 text-sm text-fg-subtle">
        Files contain only the retrieved data and computed results, with region, grid, aggregation method and provenance in the header.
      </p>
    </div>
  )
}

function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">{children}</div>
}
