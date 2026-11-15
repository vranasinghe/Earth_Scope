import { TileLayer } from 'react-leaflet'

const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/**
 * OpenStreetMap basemap. index.css mutes it per theme (a filter on the tile pane only),
 * so data layers — grid cells, trend colours, boundaries — keep their true colours and carry the eye.
 */
export function BaseTiles() {
  return <TileLayer attribution={ATTRIBUTION} url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" maxZoom={18} />
}
