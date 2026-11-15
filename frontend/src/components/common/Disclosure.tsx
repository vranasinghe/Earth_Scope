import { ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

/** Collapsed secondary content: a bordered row whose summary says what is inside. */
export function Disclosure({ title, summary, children, flush = false }: { title: string; summary: string; children: ReactNode; flush?: boolean }) {
  return (
    <details className={`group rounded-xl border border-line ${flush ? '' : 'mt-6'}`}>
      <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1">
          <span className="block font-semibold text-fg">{title}</span>
          <span className="block text-sm text-fg-subtle">{summary}</span>
        </span>
        <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <div className="border-t border-line p-4 sm:p-5">{children}</div>
    </details>
  )
}
