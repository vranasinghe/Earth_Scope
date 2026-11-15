import { Droplets, Sprout, Thermometer } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { KeyboardEvent } from 'react'
import type { VariableInfo } from '../../types/api'

const VARIABLE_ICONS: Record<string, LucideIcon> = {
  T2M: Thermometer,
  RH2M: Droplets,
  GWETTOP: Sprout,
}

interface Props {
  variables: VariableInfo[]
  selected: string
  onSelect: (id: string) => void
}

/** Compact radio group; the selected variable's description appears once, below the options. */
export function VariableSelector({ variables, selected, onSelect }: Props) {
  const current = variables.find((v) => v.id === selected) ?? variables[0]
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(e.key)) return
    e.preventDefault()
    const i = variables.findIndex((v) => v.id === selected)
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : variables.length - 1
    const next = variables[(i + step) % variables.length]
    onSelect(next.id)
    ;(e.currentTarget.querySelector(`[data-id="${next.id}"]`) as HTMLButtonElement | null)?.focus()
  }
  return (
    <div>
      <div role="radiogroup" aria-label="Environmental variable" className="grid gap-2 sm:grid-cols-3" onKeyDown={move}>
        {variables.map((v) => {
          const Icon = VARIABLE_ICONS[v.parameter] ?? Thermometer
          const active = v.id === selected
          return (
            <button
              key={v.id}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active ? 0 : -1}
              data-id={v.id}
              onClick={() => onSelect(v.id)}
              className={`flex items-center gap-3 rounded-lg border px-3.5 py-3 text-left transition-colors duration-150 ${
                active ? 'border-accent bg-accent/[0.07] ring-1 ring-accent' : 'border-line-strong bg-surface hover:border-fg-subtle'
              }`}
            >
              <Icon className={`size-5 shrink-0 ${active ? 'text-accent' : 'text-fg-subtle'}`} aria-hidden />
              <span className="min-w-0">
                <span className="block font-semibold text-fg">{v.name}</span>
                <span className="stat-num block text-xs text-fg-subtle">
                  {v.parameter} · {v.unit_display}
                </span>
              </span>
            </button>
          )
        })}
      </div>
      <p className="measure mt-3 text-[0.9375rem] text-fg-muted">{current.description}</p>
    </div>
  )
}
