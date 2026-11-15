import { AlertTriangle, Info, RotateCcw } from 'lucide-react'
import type { ChatMessage } from '../../types/ai'
import { renderSafeMarkdown } from '../../utils/safeMarkdown'

export function AiChatMessage({ message, onRetry, onNewConversation }: {
  message: ChatMessage
  onRetry?: () => void
  onNewConversation?: () => void
}) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent px-3.5 py-2 text-sm text-on-accent">
          <span className="sr-only">You: </span>
          {message.content}
        </p>
      </div>
    )
  }
  if (message.role === 'notice') {
    return (
      <div className="flex gap-2 rounded-lg border border-line bg-sunken px-3 py-2 text-xs text-fg-muted" role="note">
        <Info className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
        <div className="space-y-1.5">
          <div>{renderSafeMarkdown(message.content)}</div>
          {onNewConversation && (
            <button type="button" className="font-semibold text-accent hover:underline" onClick={onNewConversation}>
              Start a new conversation for this page
            </button>
          )}
        </div>
      </div>
    )
  }
  if (message.role === 'error') {
    return (
      <div className="flex gap-2 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-fg" role="alert">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
        <div className="space-y-1.5">
          <p>{message.content}</p>
          {message.retryable && onRetry && (
            <button type="button" className="inline-flex items-center gap-1 text-xs font-semibold text-accent hover:underline" onClick={onRetry}>
              <RotateCcw className="size-3.5" aria-hidden /> Try again
            </button>
          )}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[92%] space-y-2 break-words rounded-2xl rounded-bl-md border border-line bg-raised px-3.5 py-2.5 text-sm leading-relaxed text-fg">
        <span className="sr-only">Earth Scope AI: </span>
        {renderSafeMarkdown(message.content)}
      </div>
    </div>
  )
}
