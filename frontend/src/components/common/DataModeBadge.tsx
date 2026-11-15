import { Satellite } from 'lucide-react'
import type { DataMode } from '../../types/api'

/** Always-visible indicator that the numbers on screen are real NASA POWER data. */
export function DataModeBadge({ size = 'sm' }: { mode?: DataMode; size?: 'sm' | 'lg' }) {
  const pad = size === 'lg' ? 'px-2.5 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border border-teal/40 bg-teal/10 font-semibold text-teal ${pad}`}
      title="Real data retrieved from NASA POWER"
    >
      <Satellite className="size-3.5" aria-hidden />
      Live NASA data
    </span>
  )
}
