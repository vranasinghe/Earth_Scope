import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { GeoJSON, MapContainer, Marker, Rectangle, useMap, useMapEvents } from 'react-leaflet'
import { useMapColors } from '../../theme/theme'
import { BaseTiles } from './BaseTiles'
import { WORLD_CENTER, WORLD_ZOOM } from '../../constants/locations'
import type { BBox } from '../../types/api'
import type { AreaGeometry } from '../../types/area'
import { needsUnwrap, shiftGeometry } from '../../utils/polygon'
import { roundBox } from '../../utils/region'

const WORLD_BOUNDS: L.LatLngBoundsExpression = [
  [-85.05, -540],
  [85.05, 540],
]

const handleIcon = L.divIcon({
  className: 'es-pin-wrap',
  html: '<span class="es-handle"></span>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
})

const clampLat = (v: number) => Math.max(-90, Math.min(90, v))
const clampLon = (v: number) => Math.max(-180, Math.min(180, v))

function boxFrom(a: L.LatLng, b: L.LatLng): BBox {
  let lo0 = a.lng
  let lo1 = b.lng
  // Map world copies: bring both corners back into −180…180 together.
  while (Math.min(lo0, lo1) > 180) {
    lo0 -= 360
    lo1 -= 360
  }
  while (Math.max(lo0, lo1) < -180) {
    lo0 += 360
    lo1 += 360
  }
  return roundBox({
    lat_min: clampLat(Math.min(a.lat, b.lat)),
    lat_max: clampLat(Math.max(a.lat, b.lat)),
    lon_min: clampLon(Math.min(lo0, lo1)),
    lon_max: clampLon(Math.max(lo0, lo1)),
  })
}

/** Rectangle tool: click-and-drag, or click two opposite corners (works with touch). */
function DrawLayer({ active, onDone }: { active: boolean; onDone: (b: BBox) => void }) {
  const colors = useMapColors()
  const map = useMap()
  const [start, setStart] = useState<L.LatLng | null>(null)
  const [current, setCurrent] = useState<L.LatLng | null>(null)
  const downAt = useRef<L.Point | null>(null)

  useEffect(() => {
    const el = map.getContainer()
    if (active) {
      map.dragging.disable()
      map.doubleClickZoom.disable()
      el.style.cursor = 'crosshair'
    } else {
      map.dragging.enable()
      map.doubleClickZoom.enable()
      el.style.cursor = ''
    }
    return () => {
      map.dragging.enable()
      map.doubleClickZoom.enable()
      el.style.cursor = ''
    }
  }, [active, map])

  const finish = (end: L.LatLng) => {
    if (!start) return
    const b = boxFrom(start, end)
    setStart(null)
    setCurrent(null)
    downAt.current = null
    if (b.lat_max > b.lat_min && b.lon_max > b.lon_min) onDone(b)
  }

  useMapEvents({
    mousedown(e) {
      if (!active) return
      if (!start) {
        setStart(e.latlng)
        setCurrent(e.latlng)
        downAt.current = e.containerPoint
      } else {
        finish(e.latlng) // second click of click-click mode
      }
    },
    mousemove(e) {
      if (active && start) setCurrent(e.latlng)
    },
    mouseup(e) {
      if (active && start && downAt.current && e.containerPoint.distanceTo(downAt.current) > 8) finish(e.latlng)
    },
  })

  if (!active || !start || !current) return null
  const b = boxFrom(start, current)
  return (
    <Rectangle
      bounds={[[b.lat_min, b.lon_min], [b.lat_max, b.lon_max]]}
      pathOptions={{ color: colors.accent, weight: 2, dashArray: '6 4', fillOpacity: 0.08 }}
      interactive={false}
    />
  )
}

function FitBox({ box, shapeBounds, token }: { box: BBox | null; shapeBounds: L.LatLngBounds | null; token: number }) {
  const map = useMap()
  const handled = useRef(0)
  useEffect(() => {
    if ((!box && !shapeBounds) || token === 0 || handled.current === token) return
    handled.current = token
    const target = shapeBounds ?? L.latLngBounds([box!.lat_min, box!.lon_min], [box!.lat_max, box!.lon_max])
    map.flyToBounds(target, { padding: [40, 40], duration: 0.8 })
  }, [box, shapeBounds, token, map])
  return null
}

interface Props {
  box: BBox | null
  onChange?: (b: BBox) => void
  drawing?: boolean
  onDrawingDone?: () => void
  /** Increment to fly the map to the current box. */
  focusToken?: number
  editable?: boolean
  /** Draw the region outline (default true). */
  showBox?: boolean
  /** Country / polygon outline (GeoJSON, WGS84). Shapes split at ±180° are drawn on one side. */
  shape?: AreaGeometry | null
  className?: string
  children?: ReactNode
  /** Draw vector layers on one canvas instead of one SVG element each (large spatial maps). Display only. */
  preferCanvas?: boolean
}

export function RegionMap({ box, onChange, drawing = false, onDrawingDone, focusToken = 0, editable = false, showBox = true, shape = null, className = 'h-96', children, preferCanvas = false }: Props) {
  const colors = useMapColors()
  const shown = useMemo(() => (shape ? shiftGeometry(shape, needsUnwrap(shape)) : null), [shape])
  const shapeBounds = useMemo(() => (shown ? L.geoJSON(shown as GeoJSON.Geometry).getBounds() : null), [shown])
  const shapeKey = useMemo(() => (shown ? JSON.stringify(shown).length + ':' + JSON.stringify(shown).slice(0, 80) : ''), [shown])
  const handlers = useMemo(
    () => ({
      corner: (which: 'sw' | 'ne') => ({
        dragend(e: L.LeafletEvent) {
          if (!box || !onChange) return
          const p = (e.target as L.Marker).getLatLng()
          const other = which === 'sw' ? L.latLng(box.lat_max, box.lon_max) : L.latLng(box.lat_min, box.lon_min)
          onChange(boxFrom(p, other))
        },
      }),
    }),
    [box, onChange],
  )

  return (
    <div className={`overflow-hidden rounded-xl border border-line ${className}`}>
      <MapContainer
        center={shapeBounds ? shapeBounds.getCenter() : box ? [(box.lat_min + box.lat_max) / 2, (box.lon_min + box.lon_max) / 2] : WORLD_CENTER}
        zoom={box || shapeBounds ? 5 : WORLD_ZOOM}
        minZoom={2}
        maxBounds={WORLD_BOUNDS}
        maxBoundsViscosity={1}
        worldCopyJump
        // Cap drag inertia so a quick flick cannot fling the selected region far out of view.
        // (Leaflet's default is unlimited; 600 px/s limits a fling to roughly 265 px.)
        inertiaMaxSpeed={600}
        preferCanvas={preferCanvas}
        scrollWheelZoom={false}
        className="h-full w-full"
      >
        <BaseTiles />
        <FitBox box={box} shapeBounds={shapeBounds} token={focusToken} />
        {children}
        {shown && (
          <GeoJSON
            key={`${shapeKey}-${colors.accent}`}
            data={shown as GeoJSON.Geometry}
            style={{ color: colors.accent, weight: 2.5, fill: true, fillColor: colors.accent, fillOpacity: 0.06 }}
            interactive={false}
          />
        )}
        {box && showBox && (
          <Rectangle
            bounds={[[box.lat_min, box.lon_min], [box.lat_max, box.lon_max]]}
            pathOptions={{ color: colors.accent, weight: 2.5, fill: false }}
            interactive={false}
          />
        )}
        {box && editable && !drawing && onChange && (
          <>
            <Marker position={[box.lat_min, box.lon_min]} icon={handleIcon} draggable eventHandlers={handlers.corner('sw')} title="Drag to resize (south-west corner)" />
            <Marker position={[box.lat_max, box.lon_max]} icon={handleIcon} draggable eventHandlers={handlers.corner('ne')} title="Drag to resize (north-east corner)" />
          </>
        )}
        {onChange && (
          <DrawLayer
            active={drawing}
            onDone={(b) => {
              onChange(b)
              onDrawingDone?.()
            }}
          />
        )}
      </MapContainer>
    </div>
  )
}
