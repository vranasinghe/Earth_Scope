// Types for the Earth Scope AI assistant (mirrors backend/app/models/ai_schemas.py).

export type AiPageType =
  | 'home'
  | 'explore'
  | 'point_results'
  | 'compare_setup'
  | 'compare_results'
  | 'regional_setup'
  | 'regional_results'
  | 'jobs'
  | 'job_details'
  | 'learn'
  | 'other'

export type AiAction = 'ask' | 'summarize'

/** Spatial Trend Explorer settings sent as part of a regional reference (never numbers). */
export interface AiSpatialReference {
  method: string
  correction: string
  alpha: number
  layer?: 'magnitude' | 'direction' | 'significance' | 'availability'
  estimator?: 'sen' | 'ols'
  basis?: 'adjusted' | 'raw'
  selected_cell_id?: string | null
}

/**
 * What the current page shows, as an analysis *reference* (the parameters of the analysis, or a
 * job id). The server recomputes / reloads the actual results from it; the browser never sends
 * scientific numbers.
 */
export interface AiPageContext {
  pageType: AiPageType
  reference: Record<string, unknown> | null
  /** Short human label, e.g. "Air Temperature at Colombo, 2001–2025". */
  label: string
  /** Identifies the analysis (not UI state like the selected map layer). */
  analysisKey: string
  hasResults: boolean
}

export interface AiChatTurn {
  role: 'user' | 'assistant'
  content: string
}

export interface AiChatRequest {
  message: string
  action: AiAction
  page_type: AiPageType
  reference: Record<string, unknown> | null
  history: AiChatTurn[]
  earlier_summary?: string | null
}

export interface AiChatResponse {
  reply: string
  context_id: string | null
  context_label: string | null
  has_results: boolean
  model: string | null
  usage: { prompt_tokens?: number; output_tokens?: number; total_tokens?: number } | null
  generated: boolean
}

export interface AiStatus {
  enabled: boolean
  configured: boolean
  available: boolean
  reason: string
  model: string | null
  message: string
  limits: { max_message_chars: number; max_history_messages: number; requests_per_minute: number; requests_per_hour: number }
  privacy_notice: string
}

export type ChatMessageRole = 'user' | 'assistant' | 'notice' | 'error'

export interface ChatMessage {
  id: string
  role: ChatMessageRole
  content: string
  /** For error messages: whether "Try again" makes sense. */
  retryable?: boolean
}
