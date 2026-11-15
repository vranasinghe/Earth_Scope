import type { Interpretation } from '../../types/api'

/** Plain-language reading of the result beside the limitations that bound it. */
export function InterpretationPanel({ interpretation }: { interpretation: Interpretation }) {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] lg:gap-12">
      <section aria-labelledby="interp-title">
        <h3 id="interp-title" className="text-lg font-bold leading-snug">
          {interpretation.headline}
        </h3>
        <div className="measure mt-3 space-y-3 leading-relaxed text-fg-muted">
          {interpretation.paragraphs.map((p) => (
            <p key={p}>{p}</p>
          ))}
        </div>
        <p className="mt-4 text-sm text-fg-subtle">Written by fixed rules from the computed statistics; no AI model writes or adjusts the findings.</p>
      </section>
      <section aria-labelledby="caveat-title" className="panel self-start p-5">
        <h3 id="caveat-title" className="font-bold">
          Keep in mind
        </h3>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-relaxed text-fg-muted marker:text-fg-subtle">
          {interpretation.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </section>
    </div>
  )
}
