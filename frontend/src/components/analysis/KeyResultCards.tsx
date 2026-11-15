import { ArrowDownRight, ArrowRight, ArrowUpRight } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Direction, EvidenceCategory, StatisticsResult } from '../../types/api'
import { formatP, formatSigned } from '../../utils/format'

const DIRECTION_ICON: Record<Direction, LucideIcon> = {
  increasing: ArrowUpRight,
  decreasing: ArrowDownRight,
  'no change': ArrowRight,
}

const EVIDENCE_TONE: Record<EvidenceCategory, { text: string; dot: string }> = {
  significant_increasing: { text: 'text-teal', dot: 'bg-teal' },
  significant_decreasing: { text: 'text-teal', dot: 'bg-teal' },
  mixed: { text: 'text-warn', dot: 'bg-warn' },
  not_significant: { text: 'text-fg', dot: 'bg-fg-subtle' },
}

function Stat({ label, value, detail, icon: Icon, mono = true }: { label: string; value: string; detail: string; icon?: LucideIcon; mono?: boolean }) {
  return (
    <div className="min-w-0 bg-surface px-5 py-4 sm:px-6">
      <dt className="text-sm text-fg-muted">{label}</dt>
      <dd className="mt-1">
        <span className={`flex items-center gap-1.5 text-xl font-semibold text-fg ${mono ? 'stat-num' : ''}`}>
          {Icon && <Icon className="size-5 text-accent" aria-hidden />}
          {value}
        </span>
        <span className="mt-0.5 block text-xs text-fg-subtle">{detail}</span>
      </dd>
    </div>
  )
}

/** The finding first (overall evidence), then the four numbers it rests on. */
export function KeyResultCards({ stats, rateUnit }: { stats: StatisticsResult; rateUnit: string }) {
  const { regression: reg, mann_kendall: mk, sens_slope: sen, evidence } = stats
  const DirIcon = DIRECTION_ICON[sen.direction]
  const dirLabel = sen.direction === 'no change' ? 'No change' : sen.direction[0].toUpperCase() + sen.direction.slice(1)
  const tone = EVIDENCE_TONE[evidence.category]

  return (
    <div className="card overflow-hidden">
      <div className="flex items-start gap-3 border-b border-line px-5 py-5 sm:px-6">
        <span className={`mt-2.5 size-2.5 shrink-0 rounded-full ${tone.dot}`} aria-hidden />
        <div>
          <p className="text-sm text-fg-muted">Overall evidence at α = {stats.alpha}</p>
          <p className={`mt-0.5 text-2xl font-bold leading-tight ${tone.text}`}>{evidence.label}</p>
          <p className="mt-1 text-sm text-fg-subtle">Combines linear regression and the Mann-Kendall test.</p>
        </div>
      </div>
      <dl className="grid gap-px bg-line min-[480px]:grid-cols-2 lg:grid-cols-4">
        <Stat
          icon={DirIcon}
          mono={false}
          label="Direction"
          value={dirLabel}
          detail={`Sen's slope · ${mk.significant ? 'significant' : 'not significant'} by Mann-Kendall`}
        />
        <Stat label="Rate of change" value={formatSigned(reg.slope)} detail={`${rateUnit} · ${formatSigned(reg.slope_per_decade)} per decade (regression)`} />
        <Stat
          label="Mann-Kendall p"
          value={formatP(mk.p_value)}
          detail={mk.p_value < stats.alpha ? `below α = ${stats.alpha}: significant` : `not below α = ${stats.alpha}`}
        />
        <Stat label="Regression R²" value={reg.r_squared.toFixed(3)} detail={`explains ${(reg.r_squared * 100).toFixed(1)}% of year-to-year variation`} />
      </dl>
    </div>
  )
}
