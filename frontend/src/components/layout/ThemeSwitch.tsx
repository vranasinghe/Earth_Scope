import { Monitor, Moon, Sun } from 'lucide-react'
import type { KeyboardEvent } from 'react'
import { useTheme } from '../../theme/theme'
import type { ThemeChoice } from '../../theme/theme'

const OPTIONS: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light theme', icon: Sun },
  { value: 'system', label: 'Match system theme', icon: Monitor },
  { value: 'dark', label: 'Dark theme', icon: Moon },
]

/** Three-way theme control (radio group: arrow keys move, the choice applies immediately and persists). */
export function ThemeSwitch() {
  const { choice, setChoice } = useTheme()
  const move = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const i = OPTIONS.findIndex((o) => o.value === choice)
    const next = OPTIONS[(i + (e.key === 'ArrowRight' ? 1 : OPTIONS.length - 1)) % OPTIONS.length]
    setChoice(next.value)
    ;(e.currentTarget.querySelector(`[data-value="${next.value}"]`) as HTMLButtonElement | null)?.focus()
  }
  return (
    <div role="radiogroup" aria-label="Colour theme" className="seg" onKeyDown={move}>
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={choice === value}
          aria-label={label}
          title={label}
          data-value={value}
          tabIndex={choice === value ? 0 : -1}
          onClick={() => setChoice(value)}
          className="seg-item min-h-7 px-2"
        >
          <Icon className="size-4" aria-hidden />
        </button>
      ))}
    </div>
  )
}
