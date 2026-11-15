import { Info } from 'lucide-react'
import { useId, useState } from 'react'

/** Small "i" button with an explanatory tooltip (hover, keyboard focus or tap; Escape closes). */
export function InfoTip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <span className="relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        // Hover and focus already open it, so a click (or tap) must not toggle it shut again.
        onClick={() => setOpen(true)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        className="ml-1 rounded-full p-0.5 text-fg-subtle hover:text-accent"
      >
        <Info className="size-3.5" aria-hidden />
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 top-full z-[1300] mt-1.5 w-64 -translate-x-1/2 rounded-lg border border-line-strong bg-surface p-3 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-fg-muted shadow-[var(--shadow-pop)]"
        >
          {text}
        </span>
      )}
    </span>
  )
}
