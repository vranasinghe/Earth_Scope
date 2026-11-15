import { Bot, Minus, SquarePen, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { KeyboardEvent } from 'react'
import { useAiChat } from '../../context/aiChatContext'
import { quickActionsFor } from '../../utils/buildAiContext'
import type { QuickAction } from '../../utils/buildAiContext'
import { AiChatInput } from './AiChatInput'
import { renderSafeMarkdown } from '../../utils/safeMarkdown'
import { AiChatMessage } from './AiChatMessage'
import { AiQuickActions } from './AiQuickActions'

export const WELCOME =
  "Hi! I'm your Earth Scope AI assistant. I can help you understand the NASA data and statistical results on this page. What would you like to know?"

const SHORT_NOTICE = 'Messages and a summary of this analysis are sent to Google Gemini. Earth Scope does not save your chat.'

export function AiChatWindow({ id, onMinimize }: { id: string; onMinimize: () => void }) {
  const chat = useAiChat()
  const { messages, pending, status, statusError, page } = chat
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const available = status?.available === true
  const unavailableText = statusError ?? (status && !status.available ? status.message : null)

  useEffect(() => {
    if (available) inputRef.current?.focus()
  }, [available])

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, pending])

  const pick = (a: QuickAction) => chat.send(a.prompt ?? a.label, a.action, a.label)
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      onMinimize()
    }
  }
  const actions = quickActionsFor(page, chat.hasSpatial)

  return (
    <div
      id={id}
      role="dialog"
      aria-modal="false"
      aria-labelledby="es-ai-title"
      onKeyDown={onKeyDown}
      className="fixed inset-x-0 bottom-0 z-[1100] flex h-[min(85dvh,640px)] flex-col overflow-hidden rounded-t-2xl border border-line bg-surface pb-[env(safe-area-inset-bottom)] text-fg shadow-2xl motion-safe:animate-[es-ai-rise_180ms_ease-out] sm:inset-x-auto sm:bottom-24 sm:right-4 sm:h-[min(600px,calc(100dvh-8rem))] sm:w-[min(400px,calc(100vw-2rem))] sm:rounded-2xl sm:pb-0"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-line bg-raised px-4 py-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent/15 text-accent">
          <Bot className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="es-ai-title" className="text-sm font-bold leading-tight">Earth Scope AI</h2>
          <p className="truncate text-xs text-fg-muted" title={page.label}>
            Understand your analysis{page.hasResults ? ` · ${page.label}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-0.5">
          <button type="button" onClick={chat.newConversation} className="es-ai-icon-btn" aria-label="New conversation (clears the chat)" title="New conversation">
            <SquarePen className="size-4" aria-hidden />
          </button>
          <button type="button" onClick={onMinimize} className="es-ai-icon-btn" aria-label="Minimize (keeps the conversation)" title="Minimize — keeps the conversation">
            <Minus className="size-4" aria-hidden />
          </button>
          <button type="button" onClick={chat.endConversation} className="es-ai-icon-btn" aria-label="End conversation (clears the chat and closes)" title="End conversation — clears the chat">
            <X className="size-4" aria-hidden />
          </button>
        </div>
      </header>

      <div ref={logRef} role="log" aria-live="polite" aria-relevant="additions" className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-4 py-4">
        <div className="flex justify-start">
          <div className="max-w-[92%] space-y-2 rounded-2xl rounded-bl-md border border-line bg-raised px-3.5 py-2.5 text-sm leading-relaxed">
            {renderSafeMarkdown(WELCOME)}
          </div>
        </div>
        {unavailableText && (
          <div className="rounded-lg border border-warn/50 bg-warn/10 px-3 py-2 text-sm" role="status">
            <p className="font-semibold">{unavailableText}</p>
            <p className="mt-1 text-xs text-fg-muted">
              The rest of Earth Scope works normally. An administrator can enable the assistant by setting GEMINI_API_KEY on the backend.
            </p>
            <button type="button" className="mt-1.5 text-xs font-semibold text-accent hover:underline" onClick={chat.refreshStatus}>
              Check again
            </button>
          </div>
        )}
        {messages.map((m) => (
          <AiChatMessage key={m.id} message={m} onRetry={chat.retryLast} onNewConversation={m.role === 'notice' ? chat.newConversation : undefined} />
        ))}
        {pending && (
          <div className="flex items-center gap-2 text-xs text-fg-muted" role="status">
            <span className="flex gap-1" aria-hidden>
              <span className="size-1.5 rounded-full bg-accent motion-safe:animate-pulse" />
              <span className="size-1.5 rounded-full bg-accent motion-safe:animate-pulse [animation-delay:150ms]" />
              <span className="size-1.5 rounded-full bg-accent motion-safe:animate-pulse [animation-delay:300ms]" />
            </span>
            Earth Scope AI is thinking…
          </div>
        )}
        {status === null && !statusError && (
          <p className="text-xs text-fg-subtle" role="status">
            Checking the AI Assistant…
          </p>
        )}
      </div>

      <div className="shrink-0 space-y-2.5 border-t border-line bg-surface px-4 py-3">
        {available && <AiQuickActions actions={actions} disabled={pending} onPick={pick} />}
        <AiChatInput
          ref={inputRef}
          disabled={!available}
          busy={pending}
          maxLength={status?.limits.max_message_chars ?? 2000}
          onSend={(t) => chat.send(t)}
        />
        <p className="text-[11px] leading-snug text-fg-subtle">{SHORT_NOTICE}</p>
      </div>
    </div>
  )
}
