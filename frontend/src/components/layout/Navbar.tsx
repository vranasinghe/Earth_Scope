import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router'
import { Logo } from './Logo'
import { ThemeSwitch } from './ThemeSwitch'

// Results pages belong to the workspace that produced them, so the right tab stays lit.
const LINKS = [
  { to: '/explore', label: 'Explore', match: ['/explore', '/results'] },
  { to: '/regional', label: 'Regional', match: ['/regional'] },
  { to: '/compare', label: 'Compare', match: ['/compare'] },
  { to: '/jobs', label: 'Jobs', match: ['/jobs'] },
  { to: '/learn', label: 'Learn', match: ['/learn'] },
]

export function Navbar() {
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const isActive = (match: string[]) => match.some((m) => pathname === m || pathname.startsWith(`${m}/`))
  const linkClass = (active: boolean) =>
    `relative rounded-md px-3 py-2 text-[0.9375rem] font-medium transition-colors duration-150 ${
      active ? 'text-fg' : 'text-fg-muted hover:text-fg'
    }`

  return (
    <header className="sticky top-0 z-[1100] border-b border-line bg-page/85 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6" aria-label="Main">
        <Link to="/" aria-label="Earth Scope home" onClick={() => setOpen(false)} className="shrink-0 rounded-md">
          <Logo />
        </Link>
        <ul className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => {
            const active = isActive(l.match)
            return (
              <li key={l.to}>
                <NavLink to={l.to} className={linkClass(active)} aria-current={active ? 'page' : undefined}>
                  {l.label}
                  {active && <span className="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-accent" aria-hidden />}
                </NavLink>
              </li>
            )
          })}
        </ul>
        <div className="ml-auto flex items-center gap-2">
          <ThemeSwitch />
          <button
            type="button"
            className="btn-ghost min-h-9 px-2 md:hidden"
            aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </button>
        </div>
      </nav>
      {open && (
        <div id="mobile-nav" className="border-t border-line bg-page px-4 pb-3 md:hidden">
          <ul className="flex flex-col pt-2">
            {LINKS.map((l) => {
              const active = isActive(l.match)
              return (
                <li key={l.to}>
                  <NavLink
                    to={l.to}
                    onClick={() => setOpen(false)}
                    aria-current={active ? 'page' : undefined}
                    className={`block rounded-md px-3 py-3 text-base font-medium ${active ? 'bg-raised text-fg' : 'text-fg-muted hover:text-fg'}`}
                  >
                    {l.label}
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </header>
  )
}
