import { SendHorizontal } from 'lucide-react'
import { forwardRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

interface Props {
  disabled: boolean
  busy: boolean
  maxLength: number
  onSend: (text: string) => void
}

/** Enter sends, Shift+Enter adds a new line. Sending is blocked while a reply is pending. */
export const AiChatInput = forwardRef<HTMLTextAreaElement, Props>(function AiChatInput({ disabled, busy, maxLength, onSend }, ref) {
  const [text, setText] = useState('')
  const canSend = !disabled && !busy && text.trim().length > 0 && text.length <= maxLength

  const submit = (e?: FormEvent) => {
    e?.preventDefault()
    if (!canSend) return
    onSend(text)
    setText('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <form onSubmit={submit} className="flex items-end gap-2">
      <label htmlFor="es-ai-input" className="sr-only">
        Ask about this analysis
      </label>
      <textarea
        id="es-ai-input"
        ref={ref}
        rows={1}
        value={text}
        disabled={disabled}
        maxLength={maxLength + 200}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask about this analysis..."
        className="input max-h-32 min-h-10 flex-1 resize-none py-2 text-sm"
        aria-describedby={text.length > maxLength ? 'es-ai-too-long' : undefined}
      />
      <button
        type="submit"
        disabled={!canSend}
        aria-label="Send message"
        className="btn-primary size-10 shrink-0 justify-center rounded-xl p-0 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <SendHorizontal className="size-4" aria-hidden />
      </button>
      {text.length > maxLength && (
        <span id="es-ai-too-long" className="sr-only">
          Message is longer than {maxLength} characters.
        </span>
      )}
    </form>
  )
})
