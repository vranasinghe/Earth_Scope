import { Search } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { CountryListItem } from '../../types/area'

interface Props {
  countries: CountryListItem[]
  selected: string | null
  onSelect: (iso3: string) => void
}

/** Accessible combobox: type to filter by name or ISO code, arrows + Enter to choose. */
export function CountrySearch({ countries, selected, onSelect }: Props) {
  const current = countries.find((c) => c.iso3 === selected) ?? null
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const listId = useId()
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = q
      ? countries.filter((c) => c.name.toLowerCase().includes(q) || c.iso3.toLowerCase() === q)
      : countries
    return list.slice(0, 60)
  }, [countries, query])

  const choose = (c: CountryListItem) => {
    onSelect(c.iso3)
    setQuery('')
    setOpen(false)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => Math.min(matches.length - 1, a + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(0, a - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && matches[active]) choose(matches[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="relative">
      <label htmlFor={`${listId}-input`} className="label">
        Search a country
      </label>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <input
          id={`${listId}-input`}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && matches[active] ? `${listId}-${matches[active].iso3}` : undefined}
          className="input pl-9 font-sans"
          placeholder={current ? `${current.name} (${current.iso3})` : 'Type a country name or ISO code…'}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
            setActive(0)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKey}
        />
      </div>
      {open && (
        <ul id={listId} role="listbox" className="absolute z-[1200] mt-1 max-h-72 w-full overflow-auto rounded-lg border border-line-strong bg-surface py-1 shadow-xl">
          {matches.length === 0 && <li className="px-3 py-2 text-sm text-fg-muted">No country matches “{query}”.</li>}
          {matches.map((c, i) => (
            <li
              key={c.iso3}
              id={`${listId}-${c.iso3}`}
              role="option"
              aria-selected={c.iso3 === selected}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(c)}
              onMouseEnter={() => setActive(i)}
              className={`flex cursor-pointer items-center justify-between gap-2 px-3 py-1.5 text-sm ${i === active ? 'bg-raised text-fg' : 'text-fg-muted'}`}
            >
              <span>{c.name}</span>
              <span className="font-mono text-[11px] text-fg-subtle">
                {c.iso3}
                {c.source !== 'geoBoundaries' ? ' · NE' : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-[11px] text-fg-subtle">
        {countries.length} boundaries · geoBoundaries gbOpen (NE = Natural Earth fallback where gbOpen has no boundary)
      </p>
    </div>
  )
}
