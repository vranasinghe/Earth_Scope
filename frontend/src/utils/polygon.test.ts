import { describe, expect, it } from 'vitest'
import type { AreaGeometry } from '../types/area'
import {
  countVertices,
  decodeGeometry,
  editableVertices,
  encodeGeometry,
  geometryBBox,
  needsUnwrap,
  parseGeoJSONText,
  selfIntersects,
  shiftGeometry,
  validateVertices,
  verticesToGeometry,
} from './polygon'
import type { LatLng } from './polygon'
import { fromRegionalSearch, shapeOf, toRegionalSearch } from './region'

const square: LatLng[] = [[6, 80], [6, 81], [7, 81], [7, 80]]

describe('drawn polygon validation', () => {
  it('accepts a simple polygon and closes it as GeoJSON [lon, lat]', () => {
    expect(validateVertices(square)).toEqual([])
    const g = verticesToGeometry(square)
    expect(g.type).toBe('Polygon')
    const ring = g.coordinates[0] as number[][]
    expect(ring[0]).toEqual([80, 6])
    expect(ring[ring.length - 1]).toEqual(ring[0])
  })
  it('rejects too few distinct vertices, collinear shapes and self-intersections', () => {
    expect(validateVertices([[0, 0], [0, 1], [0, 1]])[0]).toMatch(/three distinct/)
    expect(validateVertices([[0, 0], [1, 1], [2, 2]])[0]).toMatch(/zero area/)
    const bowtie: LatLng[] = [[0, 0], [2, 2], [0, 2], [2, 0]]
    expect(selfIntersects(bowtie)).toBe(true)
    expect(validateVertices(bowtie)[0]).toMatch(/cross/)
    expect(selfIntersects(square)).toBe(false)
  })
  it('rejects invalid coordinates and too many vertices', () => {
    expect(validateVertices([[95, 0], [0, 1], [1, 1]])[0]).toMatch(/Latitude/)
    expect(validateVertices([[Number.NaN, 0], [0, 1], [1, 1]])[0]).toMatch(/finite/)
    const many: LatLng[] = Array.from({ length: 12 }, (_, i) => [Math.sin(i), Math.cos(i)])
    expect(validateVertices(many, 10)[0]).toMatch(/At most 10/)
  })
})

describe('GeoJSON upload parsing', () => {
  it('accepts Polygon, Feature and FeatureCollection of polygons', () => {
    const poly = { type: 'Polygon', coordinates: [[[80, 6], [81, 6], [81, 7], [80, 6]]] }
    expect(parseGeoJSONText(JSON.stringify(poly)).type).toBe('Polygon')
    expect(parseGeoJSONText(JSON.stringify({ type: 'Feature', geometry: poly, properties: {} })).type).toBe('Polygon')
    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: poly }, { type: 'Feature', geometry: poly }] }
    const g = parseGeoJSONText(JSON.stringify(fc))
    expect(g.type).toBe('MultiPolygon')
    expect(countVertices(g)).toBe(6)
  })
  it('rejects non-JSON, unsupported types, bad coordinates and oversize input', () => {
    expect(() => parseGeoJSONText('not json')).toThrow(/not valid JSON/)
    expect(() => parseGeoJSONText(JSON.stringify({ type: 'Point', coordinates: [0, 0] }))).toThrow(/Unsupported/)
    expect(() => parseGeoJSONText(JSON.stringify({ type: 'Polygon', coordinates: [[[0, 0], [1, 'x'], [1, 1], [0, 0]]] }))).toThrow(/finite/)
    expect(() => parseGeoJSONText(JSON.stringify({ type: 'Polygon', coordinates: [[[0, 0], [1, 1], [0, 0]]] }))).toThrow(/four positions/)
    expect(() => parseGeoJSONText(' '.repeat(2_000_001))).toThrow(/larger than/)
    const big = { type: 'Polygon', coordinates: [[...Array.from({ length: 30 }, (_, i) => [Math.cos(i), Math.sin(i)]), [1, 0]]] }
    expect(() => parseGeoJSONText(JSON.stringify(big), 10)).toThrow(/more than 10 vertices/)
  })
  it('only single polygons without holes are editable', () => {
    expect(editableVertices(verticesToGeometry(square))).toEqual(square)
    const holed: AreaGeometry = { type: 'Polygon', coordinates: [[[0, 0], [4, 0], [4, 4], [0, 0]], [[1, 1], [2, 1], [2, 2], [1, 1]]] }
    expect(editableVertices(holed)).toBeNull()
  })
})

describe('URL encoding and area parameters', () => {
  it('round-trips polygons and multipolygons', () => {
    const g: AreaGeometry = { type: 'MultiPolygon', coordinates: [[[[80, 6], [81, 6], [81, 7], [80, 6]]], [[[90.5, 1.25], [91, 1], [91, 2], [90.5, 1.25]]]] }
    expect(decodeGeometry(encodeGeometry(g))).toEqual(g)
    expect(decodeGeometry('1,2;garbage')).toBeNull()
  })
  it('keeps country and polygon selections in the URL and never falls back to a rectangle', () => {
    const base = { variable: 'air_temperature', startYear: 2001, endYear: 2025, coverageThreshold: 0.8 }
    const c = new URLSearchParams(toRegionalSearch({ ...base, bbox: { lat_min: 5.9, lat_max: 9.8, lon_min: 79.5, lon_max: 81.9 }, area: { kind: 'country', iso3: 'LKA' } }))
    expect(shapeOf(c)).toBe('country')
    expect(fromRegionalSearch(c)?.area).toEqual({ kind: 'country', iso3: 'LKA' })
    const geometry = verticesToGeometry(square)
    const p = new URLSearchParams(toRegionalSearch({ ...base, bbox: geometryBBox(geometry), area: { kind: 'polygon', geometry, name: 'Test area' } }))
    const back = fromRegionalSearch(p)
    expect(back?.area).toEqual({ kind: 'polygon', geometry, name: 'Test area' })
    expect(back?.bbox).toEqual({ lat_min: 6, lat_max: 7, lon_min: 80, lon_max: 81 })
    p.delete('poly')
    expect(fromRegionalSearch(p)).toBeNull() // missing polygon -> no silent rectangle
    const bad = new URLSearchParams('shape=country&iso3=12&variable=T2M&start=2001&end=2020')
    expect(fromRegionalSearch(bad)).toBeNull()
  })
})

describe('date-line display', () => {
  it('unwraps shapes split at ±180° so they are drawn on one side', () => {
    const fiji: AreaGeometry = { type: 'MultiPolygon', coordinates: [[[[177, -18], [180, -18], [180, -16], [177, -18]]], [[[-180, -18], [-179, -18], [-179, -16], [-180, -18]]]] }
    expect(needsUnwrap(fiji)).toBe(true)
    const shifted = shiftGeometry(fiji, true)
    expect(geometryBBox(shifted).lon_min).toBe(177)
    expect(geometryBBox(shifted).lon_max).toBe(181)
    expect(needsUnwrap(verticesToGeometry(square))).toBe(false)
  })
})
