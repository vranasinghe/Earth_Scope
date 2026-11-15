import { Link } from 'react-router'
import { Logo } from './Logo'

/** One compact provenance + legal note, shown once per page instead of repeated in sections. */
export function Footer() {
  return (
    <footer className="mt-24 border-t border-line">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-8 text-sm text-fg-muted sm:px-6 md:flex-row md:items-start md:justify-between">
        <div className="max-w-xl space-y-2">
          <Logo size="sm" />
          <p>
            Data from the{' '}
            <a className="text-fg underline decoration-line-strong hover:decoration-accent" href="https://power.larc.nasa.gov/" target="_blank" rel="noreferrer">
              NASA LaRC POWER Project
            </a>{' '}
            (MERRA-2 reanalysis), funded through the NASA Earth Science/Applied Science Program. Model-derived values, not
            station measurements. A trend shows that something changed, not why.
          </p>
          <p className="text-fg-subtle">
            An independent educational project, not affiliated with or endorsed by NASA. Map data © OpenStreetMap contributors.
          </p>
        </div>
        <nav aria-label="Footer" className="flex gap-6 md:pt-1">
          <Link to="/learn" className="hover:text-fg">
            Methods
          </Link>
          <a href="https://power.larc.nasa.gov/docs/" target="_blank" rel="noreferrer" className="hover:text-fg">
            NASA POWER docs
          </a>
        </nav>
      </div>
    </footer>
  )
}
