import { createContext, useContext, useEffect } from 'react'
import type { AiAction, AiPageContext, AiSpatialReference, AiStatus, ChatMessage } from '../types/ai'

/**
 * Temporary AI conversation state. Held ONLY in React memory: never written to localStorage,
 * sessionStorage, cookies or the server, so a reload or closing the tab forgets it.
 */
export interface AiChatContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
  messages: ChatMessage[]
  pending: boolean
  status: AiStatus | null
  statusError: string | null
  refreshStatus: () => void
  /** What the assistant will explain right now. */
  page: AiPageContext
  hasSpatial: boolean
  send: (text: string, action?: AiAction, display?: string) => void
  retryLast: () => void
  /** Clear messages, keep the panel open (page context stays available). */
  newConversation: () => void
  /** Clear messages and close the panel. */
  endConversation: () => void
  registerPage: (ctx: AiPageContext | null) => void
  registerSpatial: (s: AiSpatialReference | null) => void
}

export const AiChatContext = createContext<AiChatContextValue | null>(null)

export function useAiChat(): AiChatContextValue {
  const v = useContext(AiChatContext)
  if (!v) throw new Error('useAiChat must be used inside <AiChatProvider>')
  return v
}

/** Pages declare what they show. No-op outside the provider (e.g. isolated page tests). */
export function useAiPageContext(ctx: AiPageContext | null): void {
  const register = useContext(AiChatContext)?.registerPage
  const k = ctx ? `${ctx.analysisKey}|${ctx.label}|${ctx.hasResults}` : ''
  useEffect(() => {
    if (!register) return
    register(ctx)
    return () => register(null)
    // `k` captures every field of ctx that matters; ctx itself is a new object each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [register, k])
}

/** The Spatial Trend Explorer reports its current test settings, map layer and selected cell. */
export function useAiSpatialContext(s: AiSpatialReference | null): void {
  const register = useContext(AiChatContext)?.registerSpatial
  const k = s ? JSON.stringify(s) : ''
  useEffect(() => {
    if (!register) return
    register(s)
    return () => register(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [register, k])
}
