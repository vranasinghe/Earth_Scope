import { FileJson, FileSpreadsheet, Map as MapIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useAiSpatialContext } from '../../context/aiChatContext'
import { SPATIAL_HELP } from '../../constants/spatialHelp'
import { useSpatialTrends } from '../../hooks/useSpatialTrends'
import type { RegionalParams } from '../../types/api'
import type { SignificanceBasis, SlopeEstimator, SpatialLayer, SpatialSettings, SpatialTrendResponse } from '../../types/spatial'
import { symmetricMax } from '../../utils/spatialColors'
import type { DisplayOptions } from '../../utils/spatialColors'
import { downloadSpatialCsv, downloadSpatialGeoJson, downloadSpatialSummary } from '../../utils/spatialExport'
import { DataModeBadge } from '../common/DataModeBadge'
import { InfoTip } from '../common/InfoTip'
import { ErrorState, LoadingState, Notice } from '../common/States'
import { GridCellInspector } from './GridCellInspector'
import { SpatialStatisticalHelp } from './SpatialStatisticalHelp'
import { SpatialTrendControls } from './SpatialTrendControls'
import type { DisplayToggles } from './SpatialTrendControls'
import { SpatialTrendLegend } from './SpatialTrendLegend'
import { SpatialTrendMap } from './SpatialTrendMap'
import { SpatialTrendSummary } from './SpatialTrendSummary'

const DEFAULT_SETTINGS: SpatialSettings = { method: 'mann_kendall', correction: 'fdr_bh', alpha: 0.05 }

export function SpatialTrendExplorer({ params }: { params: RegionalParams }) {
  const [settings, setSettings] = useState<SpatialSettings>(DEFAULT_SETTINGS)
  const spatialParams = useMemo(() => ({ ...params, ...settings }), [params, settings])
  const { data, error, loading, lastData, retry } = useSpatialTrends(spatialParams)
  // Keep the previous map on screen while a new test/correction/threshold is classified.
  const shown: SpatialTrendResponse | null = data ?? (loading ? lastData : null)

  if (error) {
    return (
      <ErrorState error={error} title="The spatial trend map could not be computed" onRetry={error.retryable ? retry : undefined}>
        {settings !== DEFAULT_SETTINGS && (
          <button type="button" className="btn-secondary" onClick={() => setSettings(DEFAULT_SETTINGS)}>
            Reset statistical settings
          </button>
        )}
      </ErrorState>
    )
  }
  if (!shown) {
    return (
      <LoadingState
        title="Computing a trend for every NASA grid cell…"
        steps={[
          '1. Reusing the regional NASA POWER grid (no extra requests per cell)',
          '2. Annual means and trend tests for every cell',
          '3. Correcting the significance for the number of cells tested',
        ]}
      />
    )
  }
  return <ExplorerBody data={shown} settings={settings} onSettings={setSettings} busy={loading} params={spatialParams} />
}

function ExplorerBody({
  data,
  settings,
  onSettings,
  busy,
  params,
}: {
  data: SpatialTrendResponse
  settings: SpatialSettings
  onSettings: (s: SpatialSettings) => void
  busy: boolean
  params: RegionalParams & SpatialSettings
}) {
  const m = data.metadata
  const [layerChoice, setLayer] = useState<SpatialLayer>('magnitude')
  const [estimator, setEstimator] = useState<SlopeEstimator>('sen')
  const [basisChoice, setBasis] = useState<SignificanceBasis>('adjusted')
  const [toggles, setToggles] = useState<DisplayToggles>({ showGrid: true, showBoundary: true, showMissing: true, showNonSignificant: true })
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const layer: SpatialLayer = data.available ? layerChoice : 'availability'
  // AI assistant: the explorer's test settings, map layer and selected cell (UI state only; the
  // server recomputes the statistics from the analysis reference).
  useAiSpatialContext({
    method: params.method,
    correction: params.correction,
    alpha: params.alpha,
    layer,
    estimator,
    basis: data.config.correction === 'none' ? 'raw' : basisChoice,
    selected_cell_id: selectedId,
  })
  const basis: SignificanceBasis = data.config.correction === 'none' ? 'raw' : basisChoice
  // Fixed per analysis + estimator; independent of the map viewport.
  const maxAbs = useMemo(() => symmetricMax(data.cells, estimator), [data.cells, estimator])
  const options: DisplayOptions = useMemo(
    () => ({ layer, estimator, basis, maxAbs, showGrid: toggles.showGrid, showMissing: toggles.showMissing, showNonSignificant: toggles.showNonSignificant }),
    [layer, estimator, basis, maxAbs, toggles.showGrid, toggles.showMissing, toggles.showNonSignificant],
  )
  const selected = data.cells.find((c) => c.id === selectedId) ?? null
  const cellParams = useMemo(() => (selected ? { ...params, cellId: selected.id } : null), [params, selected])

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <DataModeBadge mode={m.data_mode} />
        <p className="text-sm text-fg-muted">
          {data.summary.n_cells_total} grid cells, each analysed separately
          <InfoTip label="spatial trends" text={SPATIAL_HELP.spatialTrend} />
        </p>
      </div>

      {!data.available && <Notice tone="warn">{data.unavailable_reason}</Notice>}
      {data.warnings.map((w) => (
        <Notice key={w} tone="info">
          {w}
        </Notice>
      ))}

      <SpatialTrendSummary summary={data.summary} config={data.config} regional={data.regional_aggregate} rateUnit={m.rate_unit} />

      <SpatialTrendControls
        variableName={m.variable_name}
        parameter={m.parameter}
        startYear={m.start_year}
        endYear={m.end_year}
        config={data.config}
        settings={settings}
        onSettings={onSettings}
        layer={layer}
        onLayer={setLayer}
        estimator={estimator}
        onEstimator={setEstimator}
        basis={basis}
        onBasis={setBasis}
        toggles={toggles}
        onToggles={setToggles}
        trendLayersAvailable={data.available}
        busy={busy}
      />

      <div className={`grid gap-4 ${selected ? 'lg:grid-cols-[minmax(0,1fr)_24rem]' : ''}`}>
        <div className="card card-pad min-w-0">
          <SpatialTrendMap
            cells={data.cells}
            box={m.bbox}
            shape={m.geometry ?? null}
            options={options}
            showBoundary={toggles.showBoundary}
            rateUnit={m.rate_unit}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <SpatialTrendLegend
            layer={layer}
            maxAbs={maxAbs}
            rateUnit={m.rate_unit}
            variableName={m.variable_name}
            estimator={estimator}
            basis={basis}
            correction={data.config.correction}
            alpha={data.config.alpha}
            showNonSignificant={toggles.showNonSignificant}
            showMissing={toggles.showMissing}
          />
          {!selected && <p className="mt-2 text-xs text-fg-subtle">Click a grid cell to inspect its statistics and annual series.</p>}
        </div>
        {selected && cellParams && <GridCellInspector key={selected.id} params={cellParams} cell={selected} metadata={m} onClose={() => setSelectedId(null)} />}
      </div>

      <div className="card card-pad">
        <h3 className="mb-2 font-semibold">What the map shows</h3>
        <ul className="list-disc space-y-1.5 pl-5 text-sm text-fg-muted">
          {data.interpretation.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-fg-subtle">Generated by fixed rules from the computed results — no AI writes or adjusts these statements.</p>
      </div>

      <SpatialStatisticalHelp />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="card card-pad text-sm">
          <div className="flex items-center gap-2">
            <MapIcon className="size-5 text-accent" aria-hidden />
            <h3 className="font-semibold">Spatial analysis provenance</h3>
          </div>
          <dl className="mt-3 grid gap-2 text-fg-muted sm:grid-cols-2">
            <div><dt className="text-sm text-fg-subtle">Data</dt><dd>LIVE NASA DATA — {m.provider}</dd></div>
            <div><dt className="text-sm text-fg-subtle">Parameter</dt><dd>{m.parameter} · community {m.community} · {m.sources.join(', ') || 'n/a'}</dd></div>
            <div><dt className="text-sm text-fg-subtle">Resolution</dt><dd>Monthly → annual (day-weighted, ≥ {data.config.min_valid_months_per_year} months); {m.grid_resolution}</dd></div>
            <div><dt className="text-sm text-fg-subtle">Region</dt><dd className="font-mono text-xs">{m.bbox.lat_min}…{m.bbox.lat_max} lat, {m.bbox.lon_min}…{m.bbox.lon_max} lon</dd></div>
            <div><dt className="text-sm text-fg-subtle">Per-cell analysis</dt><dd>Each cell’s own annual series; ≥ {data.config.min_years} usable years; Hamed–Rao lag screen at α = {data.config.screening_alpha}</dd></div>
            <div><dt className="text-sm text-fg-subtle">Significance</dt><dd>{data.config.method_label}; {data.config.correction_label}; α = {data.config.alpha}</dd></div>
          </dl>
          <p className="mt-3 text-xs text-fg-subtle">
            NASA POWER values are modelled / satellite-derived gridded estimates (MERRA-2 here), not measurements at a station, and neighbouring cells are not independent observations. The map is not a high-resolution land-cover map.
          </p>
          {m.request_url && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-fg-muted hover:text-fg">NASA POWER regional request (shared with the regional analysis)</summary>
              <a href={m.request_url} target="_blank" rel="noreferrer" className="mt-2 block break-all rounded-lg bg-sunken p-3 font-mono text-xs text-accent">{m.request_url}</a>
            </details>
          )}
        </div>

        <div className="card card-pad">
          <h3 className="mb-3 font-semibold">Export spatial results</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
            {[
              { label: 'Spatial trend table', sub: `CSV · ${data.cells.length} cells`, icon: FileSpreadsheet, fn: downloadSpatialCsv },
              { label: 'Grid-cell map', sub: 'GeoJSON · polygons + statistics', icon: MapIcon, fn: downloadSpatialGeoJson },
              { label: 'Spatial summary', sub: 'JSON · configuration + summary', icon: FileJson, fn: downloadSpatialSummary },
            ].map(({ label, sub, icon: Icon, fn }) => (
              <button key={label} type="button" className="btn-secondary justify-start py-3" onClick={() => fn(data)}>
                <Icon className="size-5 text-accent" aria-hidden />
                <span className="text-left">
                  {label}
                  <span className="block text-xs font-normal text-fg-muted">{sub}</span>
                </span>
              </button>
            ))}
          </div>
          <p className="mt-3 text-xs text-fg-subtle">
            Exports use the active test, correction and threshold. The selected cell’s annual series can be downloaded from the inspector.
          </p>
        </div>
      </div>
    </div>
  )
}
