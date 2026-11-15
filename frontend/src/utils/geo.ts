// MERRA-2 native grid spacing (per NASA POWER documentation).
const LAT_STEP = 0.5
const LON_STEP = 0.625

/** Approximate bounds of the MERRA-2 grid cell whose centre is nearest to the point. */
export function approxGridCell(lat: number, lon: number): [[number, number], [number, number]] {
  const latC = Math.max(-90, Math.min(90, Math.round(lat / LAT_STEP) * LAT_STEP))
  const lonC = Math.round((lon + 180) / LON_STEP) * LON_STEP - 180
  return [
    [latC - LAT_STEP / 2, lonC - LON_STEP / 2],
    [latC + LAT_STEP / 2, lonC + LON_STEP / 2],
  ]
}

/** Wrap a longitude into [-180, 180). */
export function wrapLongitude(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180
}
