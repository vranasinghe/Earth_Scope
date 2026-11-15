import { ArrowLeft, ArrowRightLeft, Pencil } from 'lucide-react'
import { useMemo } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { AdvancedStatisticsPanel } from '../components/analysis/AdvancedStatisticsPanel'
import { DataTable } from '../components/analysis/DataTable'
import { ExportPanel } from '../components/analysis/ExportPanel'
import { InterpretationPanel } from '../components/analysis/InterpretationPanel'
import { KeyResultCards } from '../components/analysis/KeyResultCards'
import { OverviewPanel } from '../components/analysis/OverviewPanel'
import { SourceAttribution } from '../components/analysis/SourceAttribution'
import { StatisticsPanel } from '../components/analysis/StatisticsPanel'
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart'
import { DataModeBadge } from '../components/common/DataModeBadge'
import { Disclosure } from '../components/common/Disclosure'
import { SectionHeading } from '../components/common/SectionHeading'
import { ErrorState, LoadingState, Notice } from '../components/common/States'
import { useAiPageContext } from '../context/aiChatContext'
import { useAnalysis } from '../hooks/useAnalysis'
import { useReverseGeocode } from '../hooks/useReverseGeocode'
import { formatCoord } from '../utils/format'
import { placeLabel } from '../utils/location'
import { pointContext } from '../utils/buildAiContext'
import { fromSearch, knownPlaceName, toSearch } from '../utils/query'

const SECTIONS = [
  ['finding', 'Finding'],
  ['chart', 'Time series'],
  ['interpretation', 'Interpretation'],
  ['statistics', 'Statistics'],
  ['data', 'Data & source'],
] as const

export default function Results() {
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const params = useMemo(() => fromSearch(search), [search])
  const { data, error, loading, retry } = useAnalysis(params)
  const explicitName = params ? knownPlaceName(params.latitude, params.longitude, params.place) : undefined
  // When no name was given (map click / typed coordinates), look one up for display only.
  const nearby = useReverseGeocode(params?.latitude ?? null, params?.longitude ?? null, Boolean(params) && !explicitName)
  // AI assistant: only a loaded result is offered as context (the server recomputes it from these parameters).
  useAiPageContext(params && data ? pointContext(params, explicitName ?? (nearby ? placeLabel(nearby) : undefined), data.metadata.variable_name) : null)

  if (!params) {
    return (
      <Page>
        <Notice tone="warn">
          No analysis settings were provided. <Link to="/explore" className="text-accent underline">Set up an analysis</Link> to see results.
        </Notice>
      </Page>
    )
  }

  const editLink = `/explore${toSearch(params)}`
  const locationName = explicitName ?? (nearby ? `near ${placeLabel(nearby)}` : undefined)
  const titlePlace = explicitName ?? (nearby ? placeLabel(nearby) : formatCoord(params.latitude, params.longitude, 2))

  return (
    <Page>
      <Link to={editLink} className="btn-ghost -ml-3 mb-6">
        <ArrowLeft className="size-4" aria-hidden /> Edit analysis
      </Link>

      {loading && (
        <LoadingState
          title="Retrieving NASA POWER data…"
          steps={['Requesting the monthly record from NASA POWER', 'Cleaning fill values and aggregating annual means', 'Running regression, Mann-Kendall and Sen’s slope']}
        />
      )}

      {error && (
        <ErrorState error={error} title="The analysis could not be completed" onRetry={error.retryable ? retry : undefined}>
          <Link to={editLink} className="btn-secondary">
            <Pencil className="size-4" aria-hidden /> Edit analysis
          </Link>
          {error.suggestedVariables.map((id) => (
            <button key={id} type="button" className="btn-secondary" onClick={() => navigate(`/results${toSearch({ ...params, variable: id })}`)}>
              <ArrowRightLeft className="size-4" aria-hidden /> Analyse {humanize(id)} here instead
            </button>
          ))}
        </ErrorState>
      )}

      {data && (
        <>
          <header className="border-b border-line pb-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.25rem]">
                  {data.metadata.variable_name} at {titlePlace}
                </h1>
                <p className="mt-2 text-fg-muted">
                  <span className="stat-num">
                    {data.metadata.start_year}–{data.metadata.end_year}
                  </span>{' '}
                  ·{' '}
                  {`monthly NASA POWER ${data.metadata.parameter} for one grid cell`}
                </p>
              </div>
              <DataModeBadge mode={data.metadata.data_mode} size="lg" />
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
              {data.statistics ? (
                <KeyResultCards stats={data.statistics} rateUnit={data.metadata.rate_unit} />
              ) : (
                <Notice tone="warn">{data.analysis_message ?? 'Statistics are unavailable for this selection.'}</Notice>
              )}
            </section>

            <section id="chart" className="scroll-mt-24">
              <SectionHeading title="Time series" description="Hover to inspect values." />
              <div className="card card-pad">
                <TimeSeriesChart result={data} />
              </div>
            </section>

            <section id="interpretation" className="scroll-mt-24">
              <SectionHeading title="What this means" />
              <InterpretationPanel interpretation={data.interpretation} />
            </section>

            {data.statistics && (
              <section id="statistics" className="scroll-mt-24">
                <SectionHeading
                  title="Statistics"
                  description={`Each test reported separately, α = ${data.statistics.alpha}, on ${data.statistics.n_years} annual means (${data.statistics.first_year}–${data.statistics.last_year}).`}
                />
                <StatisticsPanel stats={data.statistics} rateUnit={data.metadata.rate_unit} />
                {data.statistics.evidence.category === 'mixed' && (
                  <div className="mt-4">
                    <Notice tone="warn">{data.statistics.evidence.explanation}</Notice>
                  </div>
                )}
                {data.statistics.advanced && (
                  <Disclosure title="Advanced statistics" summary="Do consecutive years depend on each other, and does accounting for that change the conclusion?">
                    <AdvancedStatisticsPanel stats={data.statistics} rateUnit={data.metadata.rate_unit} interpretation={data.interpretation} />
                  </Disclosure>
                )}
              </section>
            )}

            <section id="data" className="scroll-mt-24">
              <SectionHeading title="Data & source" />
              <OverviewPanel result={data} locationName={locationName} />
              <div className="mt-6 space-y-3">
                <Disclosure title={`Monthly observations (${data.monthly.length})`} summary="Every month in the period, including gaps." flush>
                  <DataTable result={data} />
                </Disclosure>
                <SourceAttribution metadata={data.metadata} />
              </div>
              <div className="mt-8">
                <h3 className="mb-3 font-bold">Export</h3>
                <ExportPanel result={data} />
              </div>
            </section>
          </div>
        </>
      )}
    </Page>
  )
}

function humanize(id: string): string {
  const s = id.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function Page({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</div>
}
