import { ArrowRight } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { ConceptCard } from '../components/common/ConceptCard'
import { CONCEPTS } from '../constants/education'
import { useAiPageContext } from '../context/aiChatContext'
import { learnContext } from '../utils/buildAiContext'

const GROUPS = [
  {
    id: 'reading',
    title: 'Reading a trend',
    intro: 'What the chart and the slope describe.',
    concepts: ['time-series', 'trend', 'positive', 'negative', 'regression', 'mann-kendall'],
  },
  {
    id: 'evidence',
    title: 'Judging the evidence',
    intro: 'How confident the statistics let you be, and what they cannot tell you.',
    concepts: ['p-value', 'significance', 'confidence-interval', 'causation'],
  },
]

const METHOD_NOTES = [
  {
    title: 'Monthly values become annual means',
    text: 'NASA POWER returns one mean per month. Each year is averaged with every month weighted by its number of days, so a 31-day month counts more than February. Years with fewer than 10 valid months are left out of the trend tests rather than filled in.',
  },
  {
    title: 'Why annual, not monthly',
    text: 'Monthly data carry a strong seasonal cycle that would swamp a slow trend. Annual means remove the cycle. They reduce — but do not remove — persistence from one year to the next (autocorrelation), which can make tests over-confident; the advanced statistics check for it.',
  },
  {
    title: 'A point is one grid cell',
    text: 'A point analysis describes one NASA POWER grid cell (about 0.5° × 0.625°), not an average for a city, country or continent. Regional and country analyses weight every cell by its true area inside the selection.',
  },
  {
    title: 'Model data, not station readings',
    text: 'Values come from the MERRA-2 reanalysis, which combines a weather model with many observations. They are not measurements from a weather station at that exact spot, and small-scale effects such as cities or coastlines may be smoothed out.',
  },
]

export default function Learn() {
  const byId = new Map(CONCEPTS.map((c) => [c.id, c]))
  // AI assistant: the section the visitor jumped to (#hash) is the concept to explain.
  const { hash } = useLocation()
  const anchor = decodeURIComponent(hash.replace(/^#/, ''))
  const topic = anchor ? (GROUPS.find((g) => g.id === anchor)?.title ?? byId.get(anchor)?.title ?? (anchor === 'data' ? 'How the data is prepared' : null)) : null
  useAiPageContext(learnContext(topic))
  return (
    <div className="mx-auto max-w-6xl px-4 pt-10 sm:px-6">
      <header className="max-w-3xl">
        <h1 className="text-3xl font-extrabold tracking-[-0.02em] sm:text-[2.5rem]">How to read a trend</h1>
        <p className="measure mt-3 text-lg text-fg-muted">
          Plain-language explanations of the statistics behind every Earth Scope result, and of how the NASA data is prepared before it is tested.
        </p>
      </header>

      <div className="mt-12 grid gap-10 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-16">
        <nav aria-label="On this page" className="hidden lg:block">
          <ul className="sticky top-24 space-y-2 text-[0.9375rem]">
            {[...GROUPS.map((g) => [g.id, g.title]), ['data', 'How the data is prepared']].map(([id, title]) => (
              <li key={id}>
                <a href={`#${id}`} className="text-fg-muted hover:text-accent">
                  {title}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-16">
          {GROUPS.map((g, gi) => (
            <section key={g.id} id={g.id} aria-labelledby={`${g.id}-h`} className="scroll-mt-24">
              <h2 id={`${g.id}-h`} className="text-2xl font-bold">
                {g.title}
              </h2>
              <p className="mt-1 text-fg-muted">{g.intro}</p>
              <div className="mt-4 border-t border-line">
                {g.concepts.map((id, i) => {
                  const c = byId.get(id)
                  return c ? <ConceptCard key={id} concept={c} defaultOpen={gi === 0 && i === 0} /> : null
                })}
              </div>
            </section>
          ))}

          <section id="data" aria-labelledby="data-h" className="scroll-mt-24">
            <h2 id="data-h" className="text-2xl font-bold">
              How the data is prepared
            </h2>
            <p className="mt-1 text-fg-muted">What happens between the NASA request and the trend test.</p>
            <div className="mt-6 grid gap-x-10 gap-y-8 sm:grid-cols-2">
              {METHOD_NOTES.map((n) => (
                <div key={n.title}>
                  <h3 className="font-bold">{n.title}</h3>
                  <p className="mt-2 leading-relaxed text-fg-muted">{n.text}</p>
                </div>
              ))}
            </div>
          </section>

          <section className="flex flex-wrap items-center justify-between gap-4 border-t border-line pt-8">
            <p className="text-lg font-bold">Ready to test a trend yourself?</p>
            <div className="flex flex-wrap gap-3">
              <Link to="/explore" className="btn-primary">
                Explore a location <ArrowRight className="size-4" aria-hidden />
              </Link>
              <Link to="/regional" className="btn-secondary">
                Analyse a region
              </Link>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
