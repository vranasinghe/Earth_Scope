import { ChevronDown } from 'lucide-react'
import type { Concept } from '../../constants/education'

/** One concept as an accordion row (native <details>: keyboard and screen-reader friendly). */
export function ConceptCard({ concept, defaultOpen = false }: { concept: Concept; defaultOpen?: boolean }) {
  return (
    <details className="group border-b border-line py-1 [&[open]_summary_svg]:rotate-180" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-md py-3 text-[1.0625rem] font-semibold text-fg hover:text-accent [&::-webkit-details-marker]:hidden">
        {concept.title}
        <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform duration-200" aria-hidden />
      </summary>
      <div className="measure pb-5 pr-8">
        <p className="leading-relaxed text-fg-muted">{concept.body}</p>
        {concept.example && <p className="mt-2 border-l-2 border-line-strong pl-3 text-sm text-fg-subtle">{concept.example}</p>}
      </div>
    </details>
  )
}
