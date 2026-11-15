import { ArrowRight, ArrowUpRight, Droplets, GitCompareArrows, Grid3x3, MapPin, Sprout, Thermometer } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { Link } from 'react-router'
import { COMPARE_EXAMPLE, EXAMPLES, presetLabel } from '../constants/locations'
import { toCompareSearch, toSearch } from '../utils/query'

// Leaflet is only downloaded when the home page map is shown.
const WorldPreviewMap = lazy(() => import('../components/map/WorldPreviewMap'))

/** Mirrors the backend's default end year: the latest normally complete year in NASA POWER. */
function defaultEndYear(): number {
  const now = new Date()
  return now.getMonth() >= 2 ? now.getFullYear() - 1 : now.getFullYear() - 2
}

const WORKFLOWS = [
  { to: '/explore', icon: MapPin, title: 'A trend at one place', text: 'Pick any point on Earth and test its monthly record since 1981.' },
  { to: '/regional', icon: Grid3x3, title: 'Regions and countries', text: 'Area-weighted trends for a rectangle, a country or your own polygon, with a per-cell significance map.' },
  { to: '/compare', icon: GitCompareArrows, title: 'Places side by side', text: 'Two or three locations on one chart, with the same method and period.' },
]

const STEPS = [
  { title: 'Choose', text: 'A variable, a place or area, and at least ten years.' },
  { title: 'Retrieve', text: 'The monthly record comes straight from the NASA POWER API.' },
  { title: 'Test', text: 'Annual means go through regression, Mann-Kendall and Sen’s slope.' },
  { title: 'Read', text: 'Results come with plain-language interpretation and their limits.' },
]

const VARIABLES = [
  { icon: Thermometer, name: 'Air temperature', param: 'T2M', unit: '°C', text: 'About 2 m above the ground. Warming or cooling?' },
  { icon: Droplets, name: 'Relative humidity', param: 'RH2M', unit: '%', text: 'How close the near-surface air is to saturation.' },
  { icon: Sprout, name: 'Soil wetness', param: 'GWETTOP', unit: '0–1', text: 'Top ~5 cm of soil, from dry (0) to saturated (1). Land only.' },
]

const VARIABLE_LABEL: Record<string, string> = {
  air_temperature: 'Air temperature',
  relative_humidity: 'Relative humidity',
  soil_wetness: 'Soil wetness',
}

export default function Home() {
  const end = defaultEndYear()
  return (
    <div>
      {/* Hero: the question, one action, and the live map as proof */}
      <section className="mx-auto grid max-w-7xl items-center gap-10 px-4 pb-16 pt-12 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-14 lg:pb-24 lg:pt-20">
        <div>
          <h1 className="max-w-[16ch] text-[2.375rem] font-extrabold leading-[1.06] tracking-[-0.025em] sm:text-5xl lg:text-[3.5rem]">
            How has this place changed — and is the change real?
          </h1>
          <p className="measure mt-6 text-lg leading-relaxed text-fg-muted">
            Earth Scope pulls the monthly NASA POWER record for any point, region or country since 1981 and tests its trend the
            way a scientist would, caveats included.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link to="/explore" className="btn-primary px-5 text-base">
              Start exploring <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Link to="/regional?shape=country" className="btn-secondary px-5 text-base">
              Analyse a country
            </Link>
          </div>
          <p className="mt-8 text-sm text-fg-subtle">Live NASA data · 1981–{end} · every latitude and longitude</p>
        </div>
        <figure className="min-w-0">
          <div className="h-80 w-full sm:h-[27rem]">
            <Suspense fallback={<div className="h-full w-full animate-pulse rounded-xl bg-raised" />}>
              <WorldPreviewMap endYear={end} />
            </Suspense>
          </div>
          <figcaption className="mt-3 flex items-center gap-2 text-sm text-fg-subtle">
            <span className="size-2.5 rounded-full bg-accent" aria-hidden />
            Click a city to open its live air-temperature trend.
          </figcaption>
        </figure>
      </section>

      {/* Entry points into the three workflows */}
      <section className="border-y border-line bg-surface/60">
        <div className="mx-auto grid max-w-7xl gap-px px-4 sm:px-6 md:grid-cols-3">
          {WORKFLOWS.map(({ to, icon: Icon, title, text }) => (
            <Link key={to} to={to} className="group flex gap-4 py-7 md:px-6 md:first:pl-0 md:last:pr-0">
              <Icon className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
              <span>
                <span className="flex items-center gap-1.5 text-[1.0625rem] font-bold text-fg group-hover:text-accent">
                  {title}
                  <ArrowRight className="size-4 -translate-x-1 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" aria-hidden />
                </span>
                <span className="mt-1 block text-[0.9375rem] text-fg-muted">{text}</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      {/* How it works, beside why significance matters */}
      <section className="mx-auto grid max-w-7xl gap-12 px-4 py-20 sm:px-6 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)] lg:gap-20">
        <div>
          <h2 className="text-2xl font-bold sm:text-[1.75rem]">How it works</h2>
          <ol className="mt-8 grid gap-x-8 gap-y-7 sm:grid-cols-2">
            {STEPS.map(({ title, text }, i) => (
              <li key={title} className="grid grid-cols-[2rem_1fr] gap-x-3">
                <span className="stat-num pt-0.5 text-sm text-accent">{String(i + 1).padStart(2, '0')}</span>
                <span>
                  <span className="block font-bold">{title}</span>
                  <span className="mt-1 block text-[0.9375rem] text-fg-muted">{text}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
        <aside className="self-start border-t border-line pt-6 lg:mt-14">
          <p className="text-xl font-bold leading-snug">Seeing a change is not the same as proving one.</p>
          <p className="mt-3 text-[0.9375rem] leading-relaxed text-fg-muted">
            Weather varies from year to year, so almost any short record slopes a little. The tests ask how likely a pattern this
            strong would be if there were no trend, and Earth Scope says plainly when methods disagree.
          </p>
          <Link to="/learn" className="mt-4 inline-flex items-center gap-1 text-[0.9375rem] font-semibold text-accent hover:underline">
            Read the concepts <ArrowRight className="size-4" aria-hidden />
          </Link>
        </aside>
      </section>

      {/* Variables + real examples */}
      <section className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] lg:gap-20">
        <div>
          <h2 className="text-2xl font-bold sm:text-[1.75rem]">Three variables, one method</h2>
          <dl className="mt-6 divide-y divide-line">
            {VARIABLES.map(({ icon: Icon, name, param, unit, text }) => (
              <div key={param} className="flex gap-4 py-4">
                <Icon className="mt-0.5 size-5 shrink-0 text-fg-subtle" aria-hidden />
                <div className="min-w-0">
                  <dt className="flex flex-wrap items-baseline gap-x-2 font-bold">
                    {name}
                    <span className="stat-num text-xs font-normal text-fg-subtle">
                      {param} · {unit}
                    </span>
                  </dt>
                  <dd className="mt-0.5 text-[0.9375rem] text-fg-muted">{text}</dd>
                </div>
              </div>
            ))}
          </dl>
        </div>

        <div>
          <h2 className="text-2xl font-bold sm:text-[1.75rem]">Open a real analysis</h2>
          <p className="mt-2 text-[0.9375rem] text-fg-muted">Computed live from NASA data (2001–{end}) when you open it. Nothing is pre-written.</p>
          <ul className="mt-5 divide-y divide-line border-y border-line">
            {EXAMPLES.map((ex) => (
              <li key={ex.title}>
                <Link
                  to={`/results${toSearch({
                    variable: ex.variable,
                    latitude: ex.location.latitude,
                    longitude: ex.location.longitude,
                    startYear: 2001,
                    endYear: end,
                    place: presetLabel(ex.location),
                  })}`}
                  className="group flex items-center justify-between gap-4 py-3.5"
                >
                  <span className="min-w-0">
                    <span className="block font-semibold text-fg group-hover:text-accent">{presetLabel(ex.location)}</span>
                    <span className="block text-sm text-fg-subtle">{VARIABLE_LABEL[ex.variable] ?? ex.variable}</span>
                  </span>
                  <ArrowUpRight className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
                </Link>
              </li>
            ))}
            <li>
              <Link
                to={`/compare${toCompareSearch({
                  variable: COMPARE_EXAMPLE.variable,
                  startYear: 2001,
                  endYear: end,
                  locations: COMPARE_EXAMPLE.locations.map((p) => ({ latitude: p.latitude, longitude: p.longitude, label: presetLabel(p) })),
                })}`}
                className="group flex items-center justify-between gap-4 py-3.5"
              >
                <span className="min-w-0">
                  <span className="block font-semibold text-fg group-hover:text-accent">New York, Tokyo and Sydney</span>
                  <span className="block text-sm text-fg-subtle">Air temperature, compared on three continents</span>
                </span>
                <ArrowUpRight className="size-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
              </Link>
            </li>
          </ul>
        </div>
      </section>
    </div>
  )
}
