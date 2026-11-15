// Worldwide convenience presets. These are shortcuts only — any point on Earth
// can be selected by searching, clicking the map or typing coordinates.
// Coordinates are approximate city centres; analyses describe the NASA POWER
// grid cell containing the point, not a city-wide average.

export interface LocationPreset {
  name: string
  country: string
  latitude: number
  longitude: number
}

export interface ContinentPresets {
  continent: string
  locations: LocationPreset[]
}

export const WORLD_PRESETS: ContinentPresets[] = [
  {
    continent: 'Asia',
    locations: [
      { name: 'Colombo', country: 'Sri Lanka', latitude: 6.9271, longitude: 79.8612 },
      { name: 'Tokyo', country: 'Japan', latitude: 35.6762, longitude: 139.6503 },
      { name: 'Mumbai', country: 'India', latitude: 19.076, longitude: 72.8777 },
      { name: 'Singapore', country: 'Singapore', latitude: 1.3521, longitude: 103.8198 },
      { name: 'Dubai', country: 'United Arab Emirates', latitude: 25.2048, longitude: 55.2708 },
      { name: 'Bangkok', country: 'Thailand', latitude: 13.7563, longitude: 100.5018 },
      { name: 'Beijing', country: 'China', latitude: 39.9042, longitude: 116.4074 },
    ],
  },
  {
    continent: 'Europe',
    locations: [
      { name: 'London', country: 'United Kingdom', latitude: 51.5072, longitude: -0.1276 },
      { name: 'Reykjavik', country: 'Iceland', latitude: 64.1466, longitude: -21.9426 },
      { name: 'Paris', country: 'France', latitude: 48.8566, longitude: 2.3522 },
      { name: 'Berlin', country: 'Germany', latitude: 52.52, longitude: 13.405 },
      { name: 'Madrid', country: 'Spain', latitude: 40.4168, longitude: -3.7038 },
      { name: 'Oslo', country: 'Norway', latitude: 59.9139, longitude: 10.7522 },
    ],
  },
  {
    continent: 'Africa',
    locations: [
      { name: 'Nairobi', country: 'Kenya', latitude: -1.2921, longitude: 36.8219 },
      { name: 'Cairo', country: 'Egypt', latitude: 30.0444, longitude: 31.2357 },
      { name: 'Cape Town', country: 'South Africa', latitude: -33.9249, longitude: 18.4241 },
      { name: 'Lagos', country: 'Nigeria', latitude: 6.5244, longitude: 3.3792 },
      { name: 'Addis Ababa', country: 'Ethiopia', latitude: 8.9806, longitude: 38.7578 },
    ],
  },
  {
    continent: 'North America',
    locations: [
      { name: 'New York', country: 'United States', latitude: 40.7128, longitude: -74.006 },
      { name: 'Los Angeles', country: 'United States', latitude: 34.0522, longitude: -118.2437 },
      { name: 'Mexico City', country: 'Mexico', latitude: 19.4326, longitude: -99.1332 },
      { name: 'Toronto', country: 'Canada', latitude: 43.6532, longitude: -79.3832 },
      { name: 'Vancouver', country: 'Canada', latitude: 49.2827, longitude: -123.1207 },
    ],
  },
  {
    continent: 'South America',
    locations: [
      { name: 'São Paulo', country: 'Brazil', latitude: -23.5505, longitude: -46.6333 },
      { name: 'Buenos Aires', country: 'Argentina', latitude: -34.6037, longitude: -58.3816 },
      { name: 'Lima', country: 'Peru', latitude: -12.0464, longitude: -77.0428 },
      { name: 'Santiago', country: 'Chile', latitude: -33.4489, longitude: -70.6693 },
    ],
  },
  {
    continent: 'Oceania',
    locations: [
      { name: 'Sydney', country: 'Australia', latitude: -33.8688, longitude: 151.2093 },
      { name: 'Melbourne', country: 'Australia', latitude: -37.8136, longitude: 144.9631 },
      { name: 'Auckland', country: 'New Zealand', latitude: -36.8485, longitude: 174.7633 },
    ],
  },
]

export const ALL_PRESETS: LocationPreset[] = WORLD_PRESETS.flatMap((c) => c.locations)

export function presetLabel(p: LocationPreset): string {
  return p.name === p.country ? p.name : `${p.name}, ${p.country}`
}

/** Preset name for coordinates, if they match one exactly. */
export function findPreset(lat: number, lon: number): LocationPreset | undefined {
  return ALL_PRESETS.find((p) => Math.abs(p.latitude - lat) < 1e-4 && Math.abs(p.longitude - lon) < 1e-4)
}

function preset(name: string): LocationPreset {
  const p = ALL_PRESETS.find((x) => x.name === name)
  if (!p) throw new Error(`Unknown preset ${name}`)
  return p
}

// World view: centred so all inhabited continents are visible.
export const WORLD_CENTER: [number, number] = [20, 0]
export const WORLD_ZOOM = 2
/** Zoom used when jumping to a selected place. */
export const PLACE_ZOOM = 6

export interface ExampleAnalysis {
  title: string
  description: string
  variable: string
  location: LocationPreset
}

// Real-data examples. Their conclusions are NOT predetermined — results come
// from the live NASA POWER data when the example is opened.
export const EXAMPLES: ExampleAnalysis[] = [
  {
    title: 'Air temperature in New York',
    description: 'Has near-surface air temperature at the New York grid cell changed since 2001?',
    variable: 'air_temperature',
    location: preset('New York'),
  },
  {
    title: 'Relative humidity in São Paulo',
    description: 'Is the air near the surface in the São Paulo grid cell becoming more or less humid?',
    variable: 'relative_humidity',
    location: preset('São Paulo'),
  },
  {
    title: 'Soil wetness in Nairobi',
    description: 'Is surface soil in the Nairobi grid cell getting wetter or drier?',
    variable: 'soil_wetness',
    location: preset('Nairobi'),
  },
  {
    title: 'Air temperature in Colombo',
    description: 'A tropical coastal example from Sri Lanka.',
    variable: 'air_temperature',
    location: preset('Colombo'),
  },
]

export const COMPARE_EXAMPLE = {
  variable: 'air_temperature',
  locations: [preset('New York'), preset('Tokyo'), preset('Sydney')],
}
