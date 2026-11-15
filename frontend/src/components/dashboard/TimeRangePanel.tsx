import type { YearLimits } from '../../utils/validation'
import { validateYears } from '../../utils/validation'
import { InfoTip } from '../common/InfoTip'

interface Props {
  start: number
  end: number
  onChange: (start: number, end: number) => void
  limits: YearLimits & { defaultEnd: number; minValidMonths: number }
  showErrors: boolean
}

export function TimeRangePanel({ start, end, onChange, limits, showErrors }: Props) {
  const error = validateYears(start, end, limits)
  const years = Array.from({ length: limits.maxYear - limits.minYear + 1 }, (_, i) => limits.minYear + i)
  const presets = [
    { label: 'Last 10 years', start: limits.defaultEnd - 9, end: limits.defaultEnd },
    { label: 'Since 2001', start: 2001, end: limits.defaultEnd },
    { label: `Since ${limits.minYear}`, start: limits.minYear, end: limits.defaultEnd },
  ]
  const showError = Boolean(error && showErrors)

  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
      <div className="grid grid-cols-[minmax(0,8rem)_auto_minmax(0,8rem)] items-end gap-2">
        <div>
          <label htmlFor="start-year" className="label">
            From
          </label>
          <select id="start-year" className="input stat-num" value={start} onChange={(e) => onChange(Number(e.target.value), end)} aria-invalid={showError}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
        <span className="pb-2.5 text-fg-subtle" aria-hidden>
          –
        </span>
        <div>
          <label htmlFor="end-year" className="label">
            To
          </label>
          <select id="end-year" className="input stat-num" value={end} onChange={(e) => onChange(start, Number(e.target.value))} aria-invalid={showError}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
                {y > limits.defaultEnd ? ' (may be incomplete)' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="seg" role="group" aria-label="Period presets">
        {presets.map((p) => (
          <button
            key={p.label}
            type="button"
            className="seg-item"
            aria-pressed={p.start === start && p.end === end}
            onClick={() => onChange(p.start, p.end)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <p className={`w-full text-sm ${showError ? 'text-danger' : 'text-fg-subtle'}`} aria-live="polite">
        {showError ? (
          error
        ) : (
          <>
            {end - start + 1} years, monthly values (minimum {limits.minSpan} years)
            <InfoTip
              label="the data resolution"
              text={`NASA POWER publishes monthly values from ${limits.minYear}, with a short delay, so the current year is usually incomplete. Trend tests use day-weighted annual means; a year counts only if it has at least ${limits.minValidMonths} valid months.`}
            />
          </>
        )}
      </p>
    </div>
  )
}
