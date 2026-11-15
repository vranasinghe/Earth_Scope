import { AlertTriangle, Info, Loader2, RotateCcw, ServerCrash } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ApiError } from '../../services/api'

/** Calm, in-place loading message; the steps say what is actually happening, not a fake progress bar. */
export function LoadingState({ title, steps }: { title: string; steps?: string[] }) {
  return (
    <div className="flex flex-col items-start gap-4 rounded-xl border border-dashed border-line-strong px-6 py-10 sm:flex-row sm:items-center" role="status" aria-live="polite">
      <Loader2 className="size-7 shrink-0 animate-spin text-accent" aria-hidden />
      <div>
        <p className="font-semibold text-fg">{title}</p>
        {steps && (
          <ol className="mt-2 space-y-0.5 text-sm text-fg-muted">
            {steps.map((s) => (
              <li key={s}>{s.replace(/^\d+\.\s*/, '')}</li>
            ))}
          </ol>
        )}
      </div>
    </div>
  )
}

export function ErrorState({
  error,
  title = 'Something went wrong',
  onRetry,
  children,
}: {
  error: ApiError
  title?: string
  onRetry?: () => void
  children?: ReactNode
}) {
  const nasaDown = error.code === 'NASA_API_UNAVAILABLE'
  const Icon = nasaDown || error.code === 'BACKEND_UNREACHABLE' ? ServerCrash : AlertTriangle
  return (
    <div className="rounded-xl border border-danger/35 bg-danger/[0.04] p-5 sm:p-6" role="alert">
      <div className="flex items-start gap-4">
        <Icon className="mt-0.5 size-6 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{title}</h2>
          <p className="mt-1 text-fg-muted">{error.message}</p>
          {error.details.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-fg-muted">
              {error.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
          {nasaDown && (
            <p className="mt-3 text-sm text-fg-subtle">
              Earth Scope never fills in missing NASA data. Please retry in a moment.
            </p>
          )}
          {(onRetry || children) && (
            <div className="mt-4 flex flex-wrap gap-3">
              {onRetry && (
                <button type="button" className="btn-primary" onClick={onRetry}>
                  <RotateCcw className="size-4" aria-hidden /> Retry
                </button>
              )}
              {children}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** Compact inline callout. `warn` for caveats that change interpretation, `info` for context. */
export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn'; children: ReactNode }) {
  const warn = tone === 'warn'
  const Icon = warn ? AlertTriangle : Info
  return (
    <div className={`flex gap-3 rounded-lg px-3.5 py-2.5 text-sm ${warn ? 'bg-warn/10 text-fg' : 'bg-raised text-fg-muted'}`}>
      <Icon className={`mt-0.5 size-4 shrink-0 ${warn ? 'text-warn' : 'text-fg-subtle'}`} aria-hidden />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
