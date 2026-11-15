import { ChevronDown, Crosshair, MapPin } from 'lucide-react'
import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'
import { WORLD_PRESETS, presetLabel } from '../../constants/locations'
import { useReverseGeocode } from '../../hooks/useReverseGeocode'
import { formatCoord } from '../../utils/format'
import { parseLocation, placeLabel } from '../../utils/location'
import type { LocationValue } from '../../utils/location'
import { parseCoordinate, validateLatitude, validateLongitude } from '../../utils/validation'
import { InfoTip } from '../common/InfoTip'
import type { MapPoint } from '../map/LocationMap'
import { LocationMap } from '../map/LocationMap'
import { LocationSearch } from '../map/LocationSearch'

interface Props {
  value: LocationValue
  onChange: (v: LocationValue) => void
  showErrors: boolean
  extraPoints?: MapPoint[]
  /** Optional content rendered under the selected point (e.g. an "Add" button). */
  actions?: ReactNode
}

/** Map-first location picker: the map leads; search, the chosen point, coordinates and examples sit in a side column. */
export function LocationPanel({ value, onChange, showErrors, extraPoints, actions }: Props) {
  const [focusToken, setFocusToken] = useState(0)
  const [continent, setContinent] = useState(WORLD_PRESETS[0].continent)
  const lat = parseCoordinate(value.latText)
  const lon = parseCoordinate(value.lonText)
  const latError = validateLatitude(lat)
  const lonError = validateLongitude(lon)
  const point = parseLocation(value)
  const empty = value.latText.trim() === '' && value.lonText.trim() === ''
  const coordError = Boolean((showErrors || !empty) && (latError || lonError))
  // Only look up a name when the user did not pick a named place.
  const nearby = useReverseGeocode(point?.lat ?? null, point?.lon ?? null, point !== null && !value.placeName)

  const select = useCallback(
    (la: number, lo: number, placeName: string | null, focus: boolean) => {
      onChange({ latText: String(la), lonText: String(lo), placeName })
      if (focus) setFocusToken((t) => t + 1)
    },
    [onChange],
  )
  const onMapSelect = useCallback((la: number, lo: number) => select(la, lo, null, false), [select])

  const presets = WORLD_PRESETS.find((c) => c.continent === continent)?.locations ?? []
  const placeText = value.placeName
    ? value.placeName
    : nearby === undefined
      ? 'Looking up the place name…'
      : nearby
        ? `Near ${placeLabel(nearby)}`
        : 'No named place here (open water or a remote area)'

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_21rem]">
      <div className="min-w-0">
        <LocationMap
          latitude={point?.lat ?? null}
          longitude={point?.lon ?? null}
          onSelect={onMapSelect}
          focusToken={focusToken}
          extraPoints={extraPoints}
          className="h-80 sm:h-[28rem]"
        />
        <p className="mt-2 flex items-center gap-1.5 text-sm text-fg-subtle">
          <Crosshair className="size-3.5 shrink-0" aria-hidden />
          Click or drag the marker. Results describe the dashed NASA grid cell, not a whole city.
          <InfoTip
            label="point-based analysis"
            text="A NASA POWER grid cell is about 0.5° × 0.625° (≈ 55 × 70 km at the equator, narrower toward the poles). The analysis describes that cell, not an average for a city, country or region."
          />
        </p>
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        <LocationSearch onSelect={(p) => select(p.latitude, p.longitude, p.place_type === 'coordinates' ? null : placeLabel(p), true)} />

        <div aria-live="polite" className="border-y border-line py-4">
          <p className="text-sm font-semibold text-fg-muted">Selected point</p>
          {point ? (
            <>
              <p className="mt-1 text-lg font-bold leading-snug text-fg">{placeText}</p>
              <p className="stat-num mt-0.5 text-sm text-fg-subtle">{formatCoord(point.lat, point.lon)}</p>
            </>
          ) : (
            <p className="mt-1 text-[0.9375rem] text-fg-muted">
              {empty ? 'None yet. Search, click the map, or pick an example below.' : 'Those coordinates are not valid yet.'}
            </p>
          )}
          {actions && <div className="mt-3">{actions}</div>}
        </div>

        <details className="disclosure" open={coordError || undefined}>
          <summary>
            <ChevronDown className="size-4 transition-transform [details[open]_&]:rotate-180" aria-hidden /> Enter coordinates
          </summary>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <CoordField
              id="lat"
              label="Latitude"
              text={value.latText}
              error={(showErrors || value.latText) && latError ? latError : null}
              help="−90 (S) to 90 (N)"
              placeholder="-33.8688"
              onText={(t) => onChange({ ...value, latText: t, placeName: null })}
              onCommit={() => point && setFocusToken((n) => n + 1)}
            />
            <CoordField
              id="lon"
              label="Longitude"
              text={value.lonText}
              error={(showErrors || value.lonText) && lonError ? lonError : null}
              help="−180 (W) to 180 (E)"
              placeholder="151.2093"
              onText={(t) => onChange({ ...value, lonText: t, placeName: null })}
              onCommit={() => point && setFocusToken((n) => n + 1)}
            />
          </div>
        </details>

        <details className="disclosure">
          <summary>
            <ChevronDown className="size-4 transition-transform [details[open]_&]:rotate-180" aria-hidden /> Example places
          </summary>
          <div className="mt-3 space-y-3">
            <label htmlFor="continent" className="sr-only">
              Continent
            </label>
            <select id="continent" className="input py-1.5 text-sm" value={continent} onChange={(e) => setContinent(e.target.value)}>
              {WORLD_PRESETS.map((c) => (
                <option key={c.continent}>{c.continent}</option>
              ))}
            </select>
            <div className="flex flex-wrap gap-1.5">
              {presets.map((p) => {
                const active = lat === p.latitude && lon === p.longitude
                return (
                  <button
                    key={p.name}
                    type="button"
                    onClick={() => select(p.latitude, p.longitude, presetLabel(p), true)}
                    aria-label={presetLabel(p)}
                    aria-pressed={active}
                    className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-sm transition-colors ${
                      active ? 'border-accent bg-accent/10 text-accent' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg'
                    }`}
                  >
                    <MapPin className="size-3.5" aria-hidden />
                    {p.name}
                  </button>
                )
              })}
            </div>
          </div>
        </details>
      </div>
    </div>
  )
}

function CoordField({
  id,
  label,
  text,
  error,
  help,
  placeholder,
  onText,
  onCommit,
}: {
  id: string
  label: string
  text: string
  error: string | null
  help: string
  placeholder: string
  onText: (t: string) => void
  onCommit: () => void
}) {
  return (
    <div>
      <label htmlFor={id} className="label">
        {label}
      </label>
      <input
        id={id}
        inputMode="decimal"
        className={`input stat-num ${error ? 'border-danger' : ''}`}
        value={text}
        onChange={(e) => onText(e.target.value)}
        onBlur={onCommit}
        placeholder={placeholder}
        aria-invalid={Boolean(error)}
        aria-describedby={`${id}-help`}
      />
      <p id={`${id}-help`} className={`mt-1 text-xs ${error ? 'text-danger' : 'text-fg-subtle'}`}>
        {error ?? help}
      </p>
    </div>
  )
}
