import { memo, useMemo } from 'react'
import { Polygon, Rectangle, Tooltip } from 'react-leaflet'
import type { BBox } from '../../types/api'
import type { AreaGeometry } from '../../types/area'
import type { SpatialTrendCell } from '../../types/spatial'
import { formatP, formatSigned } from '../../utils/format'
import { leafletPositions, needsUnwrap, shiftLon } from '../../utils/polygon'
import { cellStyle, SIGNIFICANCE_LABELS, slopeOf, statusOf } from '../../utils/spatialColors'
import type { DisplayOptions } from '../../utils/spatialColors'
import { RegionMap } from '../map/RegionMap'

interface Props {
  cells: SpatialTrendCell[]
  box: BBox
  /** Country / polygon boundary (polygon mode). */
  shape?: AreaGeometry | null
  options: DisplayOptions
  showBoundary: boolean
  rateUnit: string
  selectedId: string | null
  onSelect: (id: string) => void
}

/** Above this many cells (large countries) the map uses one canvas and no per-cell hover tooltips; a click still opens the inspector. */
const LARGE_MAP_CELLS = 2500

/** Grid cells drawn with their true MERRA-2 bounds (not equal-size pixels); in polygon mode, clipped to the boundary. */
export const SpatialTrendMap = memo(function SpatialTrendMap({ cells, box, shape = null, options, showBoundary, rateUnit, selectedId, onSelect }: Props) {
  // Styles depend only on the analysis result and the display options — never on pan/zoom.
  const styled = useMemo(() => cells.map((c) => ({ c, s: cellStyle(c, options) })), [cells, options])
  const unwrap = useMemo(() => (shape ? needsUnwrap(shape) : false), [shape])
  // Display-only optimisation: the statistics (and the FDR family) are identical whatever is drawn.
  const large = cells.length > LARGE_MAP_CELLS
  return (
    <RegionMap box={box} focusToken={1} showBox={showBoundary && !shape} shape={showBoundary ? shape : null} className="h-[24rem] sm:h-[32rem]" preferCanvas={large}>
      {styled.map(({ c, s }) => {
        if (!s.visible) return null
        const selected = c.id === selectedId
        const slope = slopeOf(c, options.estimator)
        const pathOptions = {
          fillColor: s.fillColor,
          fillOpacity: s.fillOpacity,
          color: selected ? '#22d3ee' : s.color,
          weight: selected ? 3 : s.weight,
          dashArray: selected ? undefined : s.dashArray,
        }
        const handlers = { click: () => onSelect(c.id) }
        const tooltip = large ? null : (
          <Tooltip sticky>
            <span className="text-xs">
              <strong>Cell {c.latitude}°, {c.longitude}°</strong>
              {c.overlap_fraction < 0.999 && ` · ${(c.overlap_fraction * 100).toFixed(0)}% inside`}
              <br />
              {slope !== null ? `${options.estimator === 'sen' ? 'Sen' : 'OLS'} slope ${formatSigned(slope)} ${rateUnit}` : c.reason ?? 'No trend estimate'}
              <br />
              {SIGNIFICANCE_LABELS[statusOf(c, options.basis)]}
              {c.raw_p_value !== null && ` · p ${formatP(c.raw_p_value)}`}
              {c.adjusted_p_value !== null && ` · q ${formatP(c.adjusted_p_value)}`}
              <br />
              Click for details
            </span>
          </Tooltip>
        )
        return c.clip ? (
          <Polygon key={c.id} positions={leafletPositions(c.clip, unwrap)} pathOptions={pathOptions} eventHandlers={handlers}>
            {tooltip}
          </Polygon>
        ) : (
          <Rectangle
            key={c.id}
            bounds={[[c.lat_min, shiftLon(c.lon_min, unwrap)], [c.lat_max, shiftLon(c.lon_max, unwrap)]]}
            pathOptions={pathOptions}
            eventHandlers={handlers}
          >
            {tooltip}
          </Rectangle>
        )
      })}
    </RegionMap>
  )
})
