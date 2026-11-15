// Builds the AI assistant's view of the current page: an analysis *reference* (the parameters the
// page used, or a job id) plus a label. The backend resolves the authoritative results from the
// reference, so no scientific number ever travels from the browser to the model.
import type { AnalysisParams, CompareParams, RegionalParams } from '../types/api'
import type { AiAction, AiPageContext, AiPageType } from '../types/ai'

/** Small, stable string hash (FNV-1a) so a large polygon does not bloat the analysis key. */
function hash(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(36)
}

function key(pageType: AiPageType, reference: Record<string, unknown> | null): string {
  return `${pageType}:${hash(JSON.stringify(reference ?? {}))}`
}

function make(
  pageType: AiPageType,
  reference: Record<string, unknown> | null,
  label: string,
  hasResults: boolean,
  keyFields: Record<string, unknown> | null = reference,
): AiPageContext {
  return { pageType, reference, label, hasResults, analysisKey: key(pageType, keyFields) }
}

const coord = (lat: number, lon: number) => `${lat.toFixed(2)}, ${lon.toFixed(2)}`

export function pointContext(p: AnalysisParams, place: string | undefined, variableName: string): AiPageContext {
  const where = place || coord(p.latitude, p.longitude)
  const analysis = { variable: p.variable, latitude: p.latitude, longitude: p.longitude, start_year: p.startYear, end_year: p.endYear }
  // The place name is display-only (it may resolve a moment later): it is not part of the analysis key.
  return make('point_results', { ...analysis, place: where }, `${variableName} at ${where}, ${p.startYear}–${p.endYear}`, true, analysis)
}

export function compareContext(p: CompareParams, variableName: string): AiPageContext {
  return make(
    'compare_results',
    {
      variable: p.variable,
      start_year: p.startYear,
      end_year: p.endYear,
      locations: p.locations.map((l) => ({ latitude: l.latitude, longitude: l.longitude, label: l.label })),
    },
    `${variableName} compared at ${p.locations.map((l) => l.label).join(', ')}`,
    true,
  )
}

export function regionalContext(p: RegionalParams, label: string): AiPageContext {
  if (p.jobId) return make('regional_results', { job_id: p.jobId }, label, true)
  const area =
    p.area?.kind === 'country'
      ? { kind: 'country', iso3: p.area.iso3 }
      : p.area?.kind === 'polygon'
        ? { kind: 'polygon', geometry: p.area.geometry, name: p.area.name }
        : { kind: 'rectangle', bbox: p.bbox }
  return make(
    'regional_results',
    { variable: p.variable, start_year: p.startYear, end_year: p.endYear, coverage_threshold: p.coverageThreshold, area },
    label,
    true,
  )
}

export function jobDetailsContext(jobId: string, label: string, completed: boolean): AiPageContext {
  return make('job_details', { job_id: jobId }, label, completed)
}

export function learnContext(topic: string | null): AiPageContext {
  return make('learn', topic ? { topic } : {}, topic ? `Learn: ${topic}` : 'Learn', false)
}

const PATH_PAGES: [RegExp, AiPageType, string][] = [
  [/^\/$/, 'home', 'Home'],
  [/^\/explore\/?$/, 'explore', 'Explore'],
  [/^\/compare\/?$/, 'compare_setup', 'Compare'],
  [/^\/regional\/?$/, 'regional_setup', 'Regional Analysis'],
  [/^\/jobs\/?$/, 'jobs', 'Analysis Jobs'],
  [/^\/learn\/?$/, 'learn', 'Learn'],
]

/** Context for a route when the page has not registered anything more specific (yet). */
export function defaultContextForPath(pathname: string): AiPageContext {
  for (const [re, pageType, label] of PATH_PAGES) {
    if (re.test(pathname)) return make(pageType, null, label, false)
  }
  return make('other', null, 'Earth Scope', false)
}

export interface QuickAction {
  label: string
  action: AiAction
  /** Text sent to the assistant (defaults to the label). */
  prompt?: string
}

const RESULT_ACTIONS: QuickAction[] = [
  { label: 'Summarize this analysis', action: 'summarize' },
  { label: 'Explain the trend', action: 'ask' },
  { label: 'Is this statistically significant?', action: 'ask' },
  { label: 'What does this chart mean?', action: 'ask' },
]

export function quickActionsFor(ctx: AiPageContext, hasSpatial: boolean): QuickAction[] {
  switch (ctx.pageType) {
    case 'point_results':
    case 'compare_results':
      return RESULT_ACTIONS
    case 'regional_results':
      return hasSpatial
        ? [
            RESULT_ACTIONS[0],
            { label: 'Explain this heatmap', action: 'ask' },
            { label: 'Why do cells have different colors?', action: 'ask' },
            { label: 'What is FDR correction?', action: 'ask' },
          ]
        : RESULT_ACTIONS
    case 'jobs':
    case 'job_details':
      return [
        ...(ctx.hasResults ? [RESULT_ACTIONS[0]] : []),
        { label: 'Explain this job status', action: 'ask' },
        { label: 'What happens during processing?', action: 'ask' },
      ]
    case 'learn':
      return [{ label: 'Explain this concept simply', action: 'ask' }]
    default:
      return [{ label: 'What can I analyze with Earth Scope?', action: 'ask' }]
  }
}
