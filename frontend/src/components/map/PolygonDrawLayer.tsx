import L from 'leaflet'
import { useEffect, useMemo } from 'react'
import { CircleMarker, Marker, Polygon, Polyline, useMap, useMapEvents } from 'react-leaflet'
import { useMapColors } from '../../theme/theme'
import type { LatLng } from '../../utils/polygon'

const vertexIcon = L.divIcon({ className: 'es-pin-wrap', html: '<span class="es-handle"></span>', iconSize: [14, 14], iconAnchor: [7, 7] })
const midIcon = L.divIcon({ className: 'es-pin-wrap', html: '<span class="es-handle es-handle-mid"></span>', iconSize: [10, 10], iconAnchor: [5, 5] })

interface Props {
  vertices: LatLng[]
  onChange: (v: LatLng[]) => void
  /** Drawing: each map click adds a vertex. Click the first vertex (or Finish) to close. */
  drawing: boolean
  onFinish: () => void
  invalid: boolean
}

/**
 * Custom polygon tool (no extra dependency).
 * - Drawing: click to add vertices; click the first vertex to close (≥ 3 vertices).
 * - Editing: drag a vertex to move it; click a small mid-edge handle to insert a vertex;
 *   right-click (or Alt-click) a vertex to delete it (at least three remain).
 */
export function PolygonDrawLayer({ vertices, onChange, drawing, onFinish, invalid }: Props) {
  const colors = useMapColors()
  const map = useMap()

  useEffect(() => {
    const el = map.getContainer()
    if (drawing) {
      map.doubleClickZoom.disable()
      el.style.cursor = 'crosshair'
    }
    return () => {
      map.doubleClickZoom.enable()
      el.style.cursor = ''
    }
  }, [drawing, map])

  useMapEvents({
    click(e) {
      if (!drawing) return
      onChange([...vertices, [e.latlng.lat, e.latlng.lng]])
    },
    dblclick() {
      if (drawing && vertices.length >= 3) onFinish()
    },
  })

  const mids = useMemo(
    () =>
      drawing || vertices.length < 3
        ? []
        : vertices.map((v, i) => {
            const w = vertices[(i + 1) % vertices.length]
            return { i, pos: [(v[0] + w[0]) / 2, (v[1] + w[1]) / 2] as LatLng }
          }),
    [vertices, drawing],
  )

  if (vertices.length === 0) return null
  const color = invalid ? colors.danger : colors.accent
  return (
    <>
      {drawing ? (
        <Polyline positions={vertices} pathOptions={{ color, weight: 2.5, dashArray: '6 4' }} interactive={false} />
      ) : (
        vertices.length >= 3 && <Polygon positions={vertices} pathOptions={{ color, weight: 2.5, fillColor: color, fillOpacity: 0.08 }} interactive={false} />
      )}
      {drawing && vertices.length >= 3 && (
        <CircleMarker
          center={vertices[0]}
          radius={11}
          pathOptions={{ color: colors.warn, weight: 2, fillOpacity: 0.15 }}
          eventHandlers={{ click: (e) => { L.DomEvent.stopPropagation(e); onFinish() } }}
        />
      )}
      {vertices.map((v, i) => (
        <Marker
          key={`v${i}`}
          position={v}
          icon={vertexIcon}
          draggable={!drawing}
          title={drawing ? (i === 0 ? 'First vertex — click to close the polygon' : `Vertex ${i + 1}`) : 'Drag to move · right-click or Alt-click to delete'}
          eventHandlers={{
            click: (e) => {
              const ev = e.originalEvent as MouseEvent | undefined
              if (drawing && i === 0 && vertices.length >= 3) onFinish()
              else if (!drawing && ev?.altKey && vertices.length > 3) onChange(vertices.filter((_, k) => k !== i))
            },
            contextmenu: () => {
              if (!drawing && vertices.length > 3) onChange(vertices.filter((_, k) => k !== i))
            },
            dragend: (e) => {
              const p = (e.target as L.Marker).getLatLng()
              onChange(vertices.map((x, k) => (k === i ? [p.lat, p.lng] : x)))
            },
          }}
        />
      ))}
      {mids.map(({ i, pos }) => (
        <Marker
          key={`m${i}`}
          position={pos}
          icon={midIcon}
          title="Click to add a vertex here"
          eventHandlers={{ click: () => onChange([...vertices.slice(0, i + 1), pos, ...vertices.slice(i + 1)]) }}
        />
      ))}
    </>
  )
}
