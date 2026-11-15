import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation } from 'react-router'
import { ApiError } from '../services/api'
import { aiApi } from '../services/aiApi'
import type { AiAction, AiChatTurn, AiPageContext, AiSpatialReference, AiStatus, ChatMessage } from '../types/ai'
import { defaultContextForPath } from '../utils/buildAiContext'
import { AiChatContext } from './aiChatContext'
import type { AiChatContextValue } from './aiChatContext'

/** Messages kept on screen (the request itself sends at most `max_history_messages`). */
const MAX_DISPLAY_MESSAGES = 60
const EARLIER_SUMMARY_CHARS = 1200
const UNAVAILABLE = 'AI Assistant is temporarily unavailable. Please try again.'

let seq = 0
const nextId = () => `m${Date.now().toString(36)}${(seq++).toString(36)}`
const bound = (m: ChatMessage[]) => (m.length > MAX_DISPLAY_MESSAGES ? m.slice(-MAX_DISPLAY_MESSAGES) : m)

function afterLastNotice(m: ChatMessage[]): ChatMessage[] {
  for (let i = m.length - 1; i >= 0; i--) if (m[i].role === 'notice') return m.slice(i + 1)
  return m
}

function friendly(err: unknown): { text: string; retryable: boolean } {
  if (err instanceof ApiError) {
    if (err.code === 'BACKEND_UNREACHABLE' || err.code === 'INVALID_RESPONSE') return { text: UNAVAILABLE, retryable: true }
    return { text: err.message || UNAVAILABLE, retryable: err.retryable }
  }
  return { text: UNAVAILABLE, retryable: true }
}

export function AiChatProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const [open, setOpenState] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState(false)
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [registered, setRegistered] = useState<AiPageContext | null>(null)
  const [spatial, setSpatial] = useState<AiSpatialReference | null>(null)

  // Latest messages for event handlers (send / retry) without re-creating them on every message.
  const messagesRef = useRef(messages)
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])
  const pendingRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const conversationKey = useRef<string | null>(null)
  const lastRequest = useRef<{ text: string; action: AiAction; display?: string } | null>(null)

  const page = registered ?? defaultContextForPath(pathname)
  const hasSpatial = page.pageType === 'regional_results' && spatial !== null
  const reference = useMemo(
    () => (hasSpatial ? { ...(page.reference ?? {}), spatial } : page.reference),
    [hasSpatial, page.reference, spatial],
  )

  // Context changes: never let an earlier analysis be mistaken for the current one.
  useEffect(() => {
    const k = page.analysisKey
    if (conversationKey.current === null || conversationKey.current === k) {
      conversationKey.current = k
      return
    }
    conversationKey.current = k
    setMessages((m) => {
      if (!m.some((x) => x.role === 'user')) return m
      const notice: ChatMessage = {
        id: nextId(),
        role: 'notice',
        content: page.hasResults
          ? `You're now viewing a different analysis: **${page.label}**. My next answers will use this analysis only.`
          : `You're now on **${page.label}**, which has no analysis results. Earlier answers referred to the previous analysis.`,
      }
      return bound(m[m.length - 1]?.role === 'notice' ? [...m.slice(0, -1), notice] : [...m, notice])
    })
  }, [page.analysisKey, page.hasResults, page.label])

  const loadStatus = useCallback(() => {
    aiApi
      .status()
      .then((s) => setStatus(s))
      .catch((err) => {
        setStatus(null)
        setStatusError(friendly(err).text)
      })
  }, [])

  useEffect(() => {
    if (open && status === null && statusError === null) loadStatus()
  }, [open, status, statusError, loadStatus])

  const cancelPending = useCallback(() => {
    generation.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    pendingRef.current = false
    setPending(false)
  }, [])

  const send = useCallback(
    (text: string, action: AiAction = 'ask', display?: string) => {
      if (pendingRef.current) return // no duplicate submissions while a reply is on its way
      const trimmed = text.trim()
      if (action === 'ask' && !trimmed) return
      const limit = status?.limits.max_message_chars ?? 2000
      if (trimmed.length > limit) {
        setMessages((m) =>
          bound([...m, { id: nextId(), role: 'error', content: `Your message is too long. Please keep it under ${limit} characters.` }]),
        )
        return
      }
      const since = afterLastNotice(messagesRef.current).filter((m) => m.role === 'user' || m.role === 'assistant')
      const maxHistory = status?.limits.max_history_messages ?? 20
      const recent = since.slice(-maxHistory)
      const older = since.slice(0, Math.max(0, since.length - maxHistory)).filter((m) => m.role === 'user')
      const earlier = older.length
        ? `Earlier in this conversation the user asked: ${older.map((m) => m.content.slice(0, 120)).join(' | ')}`.slice(0, EARLIER_SUMMARY_CHARS)
        : null
      const history: AiChatTurn[] = recent.map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

      lastRequest.current = { text: trimmed, action, display }
      pendingRef.current = true
      setPending(true)
      setMessages((m) => bound([...m, { id: nextId(), role: 'user', content: display ?? trimmed }]))
      const gen = generation.current
      const controller = new AbortController()
      abortRef.current = controller
      aiApi
        .chat(
          { message: action === 'ask' ? trimmed : '', action, page_type: page.pageType, reference, history, earlier_summary: earlier },
          controller.signal,
        )
        .then((res) => {
          if (gen !== generation.current) return
          setMessages((m) => bound([...m, { id: nextId(), role: 'assistant', content: res.reply }]))
        })
        .catch((err) => {
          if (gen !== generation.current || (err as Error)?.name === 'AbortError') return
          const f = friendly(err)
          if (err instanceof ApiError && err.code === 'AI_NOT_CONFIGURED') loadStatus()
          setMessages((m) => bound([...m, { id: nextId(), role: 'error', content: f.text, retryable: f.retryable }]))
        })
        .finally(() => {
          if (gen !== generation.current) return
          abortRef.current = null
          pendingRef.current = false
          setPending(false)
        })
    },
    [page.pageType, reference, status, loadStatus],
  )

  const retryLast = useCallback(() => {
    const last = lastRequest.current
    if (!last || pendingRef.current) return
    // Drop the failed exchange (its user message + error) and send it again. The ref is updated
    // synchronously so the re-sent request's history does not include the failed question.
    const out = [...messagesRef.current]
    if (out[out.length - 1]?.role === 'error') out.pop()
    if (out[out.length - 1]?.role === 'user') out.pop()
    messagesRef.current = out
    setMessages(out)
    send(last.text, last.action, last.display)
  }, [send])

  const newConversation = useCallback(() => {
    cancelPending()
    lastRequest.current = null
    conversationKey.current = page.analysisKey
    messagesRef.current = []
    setMessages([])
  }, [cancelPending, page.analysisKey])

  const endConversation = useCallback(() => {
    newConversation()
    setOpenState(false)
  }, [newConversation])

  const setOpen = useCallback((o: boolean) => setOpenState(o), [])
  const toggle = useCallback(() => setOpenState((o) => !o), [])
  const refreshStatus = useCallback(() => {
    setStatus(null)
    setStatusError(null)
  }, [])
  const registerPage = useCallback((ctx: AiPageContext | null) => setRegistered(ctx), [])
  const registerSpatial = useCallback((s: AiSpatialReference | null) => setSpatial(s), [])

  useEffect(() => () => abortRef.current?.abort(), [])

  const value: AiChatContextValue = {
    open,
    setOpen,
    toggle,
    messages,
    pending,
    status,
    statusError,
    refreshStatus,
    page,
    hasSpatial,
    send,
    retryLast,
    newConversation,
    endConversation,
    registerPage,
    registerSpatial,
  }
  return <AiChatContext.Provider value={value}>{children}</AiChatContext.Provider>
}
