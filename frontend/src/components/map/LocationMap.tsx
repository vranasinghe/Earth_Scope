import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef } from 'react'
import { CircleMarker, MapContainer, Marker, Rectangle, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { useMapColors } from '../../theme/theme'
import { BaseTiles } from './BaseTiles'
import { PLACE_ZOOM, WORLD_CENTER, WORLD_ZOOM } from '../../constants/locations'
import { approxGridCell, wrapLongitude } from '../../utils/geo'

export interface MapPoint {
  latitude: number
  longitude: number
  label: string
  color: string
}

// Web-Mercator tiles cannot show beyond ~±85° latitude; points closer to the
// poles can still be entered as coordinates (NASA POWER covers them).
const WORLD_BOUNDS: L.LatLngBoundsExpression = [
  [-85.05, -540],
  [85.05, 540],
]

const pinIcon = L.divIcon({
  className: 'es-pin-wrap',
  html: '<span class="es-pin"></span>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
})

function round4(n: number) {
  return Number(n.toFixed(4))
}

function ClickHandler({ onSelect }: { onSelect: (lat: number, lon: number) => void }) {
  useMapEvents({
    click(e) {
      onSelect(round4(e.latlng.lat), round4(wrapLongitude(e.latlng.lng)))
    },
  })
  return null
}

/** Flies to the point whenever `focusToken` changes (search, preset, typed coordinates). */
function FocusOnPoint({ lat, lon, focusToken }: { lat: number; lon: number; focusToken: number }) {
  const map = useMap()
  const handled = useRef(0)
  useEffect(() => {
    // Fly only when a new focus is requested — not on every marker drag or map click.
    if (focusToken === 0 || handled.current === focusToken) return
    handled.current = focusToken
    map.flyTo([lat, lon], Math.max(map.getZoom(), PLACE_ZOOM), { duration: 0.8 })
  }, [focusToken, lat, lon, map])
  return null
}

interface Props {
  latitude: number | null
  longitude: number | null
  onSelect: (lat: number, lon: number) => void
  /** Increment to recentre the map on the current point. */
  focusToken?: number
  /** Additional, non-editable points (e.g. locations already added to a comparison). */
  extraPoints?: MapPoint[]
  className?: string
}

export function LocationMap({ latitude, longitude, onSelect, focusToken = 0, extraPoints = [], className = 'h-80' }: Props) {
  const colors = useMapColors()
  const hasPoint = latitude !== null && longitude !== null
  const handlers = useMemo(
    () => ({
      dragend(e: L.LeafletEvent) {
        const ll = (e.target as L.Marker).getLatLng()
        onSelect(round4(Math.max(-90, Math.min(90, ll.lat))), round4(wrapLongitude(ll.lng)))
      },
    }),
    [onSelect],
  )

  return (
    <div className={`overflow-hidden rounded-xl border border-line ${className}`}>
      <MapContainer
        center={hasPoint ? [latitude, longitude] : WORLD_CENTER}
        zoom={hasPoint ? PLACE_ZOOM : WORLD_ZOOM}
        minZoom={2}
        maxBounds={WORLD_BOUNDS}
        maxBoundsViscosity={1}
        worldCopyJump
        // Page scrolling should not hijack the map; zoom with the +/− buttons, double-click or pinch.
        scrollWheelZoom={false}
        className="h-full w-full"
      >
        <BaseTiles />
        <ClickHandler onSelect={onSelect} />
        {extraPoints.map((p, i) => (
          <CircleMarker
            key={`${p.latitude},${p.longitude}`}
            center={[p.latitude, p.longitude]}
            radius={9}
            pathOptions={{ color: colors.surface, weight: 2, fillColor: p.color, fillOpacity: 1 }}
          >
            <Tooltip direction="top" offset={[0, -8]} permanent>
              {i + 1}. {p.label}
            </Tooltip>
          </CircleMarker>
        ))}
        {hasPoint && (
          <>
            <FocusOnPoint lat={latitude} lon={longitude} focusToken={focusToken} />
            <Rectangle
              bounds={approxGridCell(latitude, longitude)}
              pathOptions={{ color: colors.accent, weight: 1.5, dashArray: '4 4', fillOpacity: 0.08 }}
              interactive={false}
            />
            <Marker position={[latitude, longitude]} icon={pinIcon} draggable eventHandlers={handlers}>
              <Tooltip direction="top" offset={[0, -10]}>
                {latitude.toFixed(4)}, {longitude.toFixed(4)} — drag to adjust
              </Tooltip>
            </Marker>
          </>
        )}
      </MapContainer>
    </div>
  )
}
