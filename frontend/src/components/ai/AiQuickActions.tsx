import type { QuickAction } from '../../utils/buildAiContext'

export function AiQuickActions({ actions, disabled, onPick }: {
  actions: QuickAction[]
  disabled: boolean
  onPick: (a: QuickAction) => void
}) {
  if (!actions.length) return null
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Suggested questions">
      {actions.map((a) => (
        <button
          key={a.label}
          type="button"
          disabled={disabled}
          onClick={() => onPick(a)}
          className="rounded-full border border-line bg-surface px-3 py-1 text-xs font-medium text-fg-muted transition-colors hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {a.label}
        </button>
      ))}
    </div>
  )
}
