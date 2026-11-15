import { Bot, ChevronDown } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useAiChat } from '../../context/aiChatContext'
import { AiChatWindow } from './AiChatWindow'

const PANEL_ID = 'es-ai-panel'

/**
 * Floating "Ask me" launcher + chat panel, mounted once in the layout so it survives route
 * changes. Minimizing hides the panel but keeps the conversation; "End conversation" clears it.
 */
export function AiChat() {
  const { open, toggle, setOpen } = useAiChat()
  const launcherRef = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(open)

  // Return focus to the launcher when the panel closes (keyboard users are not stranded).
  useEffect(() => {
    if (wasOpen.current && !open) launcherRef.current?.focus()
    wasOpen.current = open
  }, [open])

  return (
    <>
      {open && <AiChatWindow id={PANEL_ID} onMinimize={() => setOpen(false)} />}
      <div
        className={`fixed right-4 z-[1100] items-center gap-3 bottom-[calc(1rem+env(safe-area-inset-bottom))] sm:right-6 sm:bottom-6 ${
          open ? 'hidden sm:flex' : 'flex'
        }`}
      >
        {!open && (
          <span
            aria-hidden
            className="relative rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-semibold text-fg shadow-md motion-safe:animate-[es-ai-fade_400ms_ease-out_both]"
          >
            Ask me
            <span className="absolute -right-1 top-1/2 size-2 -translate-y-1/2 rotate-45 border-r border-t border-line bg-surface" />
          </span>
        )}
        <button
          ref={launcherRef}
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls={open ? PANEL_ID : undefined}
          aria-label={open ? 'Minimize Earth Scope AI' : 'Open Earth Scope AI assistant'}
          className="grid size-12 place-items-center rounded-full bg-accent text-on-accent shadow-lg ring-1 ring-black/5 transition-transform hover:scale-105 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transition-none motion-reduce:hover:scale-100"
        >
          {open ? <ChevronDown className="size-6" aria-hidden /> : <Bot className="size-6" aria-hidden />}
        </button>
      </div>
    </>
  )
}
