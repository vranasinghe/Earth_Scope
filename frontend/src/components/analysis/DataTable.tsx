import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { SeriesView } from '../../types/api'
import { decimalsFor, formatFixed, monthName } from '../../utils/format'

type Mode = 'monthly' | 'annual'
type Filter = 'all' | 'valid' | 'gaps'
const PAGE_SIZE = 24

const STATUS_STYLE: Record<string, string> = {
  valid: 'text-teal',
  complete: 'text-teal',
  missing: 'text-warn',
  insufficient_coverage: 'text-warn',
  invalid: 'text-danger',
  incomplete: 'text-warn',
}

const STATUS_TEXT: Record<string, string> = {
  valid: 'Valid',
  missing: 'Missing (NASA fill value / not available)',
  invalid: 'Invalid (outside physical range) — removed',
  complete: 'Complete — used in trend tests',
  incomplete: 'Incomplete — excluded from trend tests',
  insufficient_coverage: 'Insufficient spatial coverage — excluded',
}

interface TableRow {
  key: string
  date: string
  value: number | null
  status: string
  extra: string
}

export function DataTable({ result }: { result: SeriesView }) {
  const [mode, setMode] = useState<Mode>('monthly')
  const [filter, setFilter] = useState<Filter>('all')
  const [page, setPage] = useState(0)
  const decimals = decimalsFor(result.metadata.parameter) + (mode === 'annual' ? 1 : 0)
  const unit = result.metadata.unit_display

  const rows = useMemo<TableRow[]>(() => {
    const all: TableRow[] =
      mode === 'monthly'
        ? result.monthly.map((m) => ({ key: m.date, date: `${monthName(m.month)} ${m.year}`, value: m.value, status: m.status, extra: '' }))
        : result.annual.map((a) => ({
            key: String(a.year),
            date: String(a.year),
            value: a.value,
            status: a.status === 'missing' ? 'missing' : a.status,
            extra: `${a.valid_months}/12`,
          }))
    if (filter === 'valid') return all.filter((r) => r.status === 'valid' || r.status === 'complete')
    if (filter === 'gaps') return all.filter((r) => r.status !== 'valid' && r.status !== 'complete')
    return all
  }, [mode, filter, result])

  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const current = Math.min(page, pages - 1)
  const visible = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE)

  const select = (fn: () => void) => {
    fn()
    setPage(0)
  }

  return (
    <div className="card card-pad">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Table resolution" className="inline-flex rounded-lg border border-line-strong bg-sunken p-0.5">
          {(['monthly', 'annual'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => select(() => setMode(m))}
              className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize ${mode === m ? 'bg-accent/15 text-accent' : 'text-fg-muted hover:text-fg'}`}
            >
              {m}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-fg-muted">
          Show
          <select className="input w-auto py-1.5 font-sans" value={filter} onChange={(e) => select(() => setFilter(e.target.value as Filter))}>
            <option value="all">All records</option>
            <option value="valid">Valid only</option>
            <option value="gaps">Missing / excluded only</option>
          </select>
        </label>
        <span className="ml-auto text-sm text-fg-subtle">{rows.length} records</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <caption className="sr-only">{`${result.metadata.variable_name} ${mode} observations`}</caption>
          <thead>
            <tr className="border-b border-line text-left text-sm text-fg-subtle">
              <th scope="col" className="py-2 pr-4 font-semibold">{mode === 'monthly' ? 'Date' : 'Year'}</th>
              <th scope="col" className="py-2 pr-4 text-right font-semibold">Observed value</th>
              <th scope="col" className="py-2 pr-4 font-semibold">Unit</th>
              {mode === 'annual' && <th scope="col" className="py-2 pr-4 font-semibold">Valid months</th>}
              <th scope="col" className="py-2 font-semibold">Data availability</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.key} className="border-b border-line/50 last:border-0">
                <td className="stat-num py-2 pr-4 text-fg">{r.date}</td>
                <td className="stat-num py-2 pr-4 text-right text-fg">
                  {/* Monthly values are shown exactly as NASA returned them; annual means are rounded. */}
                  {r.value === null ? '—' : mode === 'monthly' ? String(r.value) : formatFixed(r.value, decimals)}
                </td>
                <td className="py-2 pr-4 text-fg-muted">{unit}</td>
                {mode === 'annual' && <td className="stat-num py-2 pr-4 text-fg-muted">{r.extra}</td>}
                <td className={`py-2 ${STATUS_STYLE[r.status] ?? 'text-fg-muted'}`}>{STATUS_TEXT[r.status] ?? r.status}</td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={5} className="py-6 text-center text-fg-subtle">
                  No records match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2 text-sm text-fg-muted">
          <button type="button" className="btn-ghost px-2 py-1" disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
            <ChevronLeft className="size-4" />
          </button>
          <span className="stat-num">
            Page {current + 1} / {pages}
          </span>
          <button type="button" className="btn-ghost px-2 py-1" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page">
            <ChevronRight className="size-4" />
          </button>
        </div>
      )}
    </div>
  )
}
