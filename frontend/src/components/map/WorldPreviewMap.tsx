import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, Tooltip } from 'react-leaflet'
import { useMapColors } from '../../theme/theme'
import { BaseTiles } from './BaseTiles'
import { useNavigate } from 'react-router'
import type { LatLngBoundsExpression } from 'leaflet'
import { ALL_PRESETS, presetLabel } from '../../constants/locations'
import { toSearch } from '../../utils/query'

const WORLD_FIT: LatLngBoundsExpression = [
  [-50, -150],
  [70, 178],
]

/** Home-page world map. Example cities link to a live air-temperature analysis. */
export default function WorldPreviewMap({ endYear }: { endYear: number }) {
  const navigate = useNavigate()
  const colors = useMapColors()
  return (
    <div className="h-full w-full overflow-hidden rounded-xl border border-line">
      <MapContainer
        // Fit all inhabited continents into whatever width the card has.
        bounds={WORLD_FIT}
        zoomSnap={0.25}
        minZoom={0.5}
        scrollWheelZoom={false}
        worldCopyJump
        className="h-full w-full"
        attributionControl
      >
        <BaseTiles />
        {ALL_PRESETS.map((p) => (
          <CircleMarker
            key={p.name}
            center={[p.latitude, p.longitude]}
            radius={6}
            pathOptions={{ color: colors.surface, weight: 2, fillColor: colors.accent, fillOpacity: 1 }}
            eventHandlers={{
              click: () =>
                navigate(
                  `/results${toSearch({
                    variable: 'air_temperature',
                    latitude: p.latitude,
                    longitude: p.longitude,
                    startYear: 2001,
                    endYear,
                    place: presetLabel(p),
                  })}`,
                ),
            }}
          >
            <Tooltip direction="top" offset={[0, -6]}>
              {presetLabel(p)} — click for air-temperature trend
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
