/** Earth Scope mark: a globe ring, a rising trend line across it, and the observation point. */
export function Logo({ className = '', size = 'md' }: { className?: string; size?: 'sm' | 'md' }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <svg viewBox="0 0 64 64" className={size === 'sm' ? 'size-6' : 'size-7'} aria-hidden>
        <circle cx="32" cy="32" r="20" fill="none" className="stroke-accent" strokeWidth="4.5" />
        <path d="M12 37c9-2 13-11 20-11s11 9 20 7" fill="none" className="stroke-teal" strokeWidth="4.5" strokeLinecap="round" />
        <circle cx="47" cy="17" r="5" className="fill-accent" />
      </svg>
      <span className={`whitespace-nowrap font-display font-bold tracking-[-0.01em] text-fg ${size === 'sm' ? 'text-base' : 'text-lg'}`}>
        Earth Scope
      </span>
    </span>
  )
}
