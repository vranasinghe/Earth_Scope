import { describe, expect, it } from 'vitest'
import { makeCell, makeResponse } from '../test/spatialFixture'
import { cellStyle, divergingColor, niceCeil, symmetricMax } from './spatialColors'
import type { DisplayOptions } from './spatialColors'
import { cellSeriesCsv, SPATIAL_CSV_COLUMNS, spatialCsv, spatialGeoJson } from './spatialExport'

const rgb = (s: string) => s.match(/\d+/g)!.map(Number)
const opts = (o: Partial<DisplayOptions> = {}): DisplayOptions => ({
  layer: 'magnitude', estimator: 'sen', basis: 'adjusted', maxAbs: 0.05, showGrid: true, showMissing: true, showNonSignificant: true, ...o,
})

describe('diverging colour scale', () => {
  it('is neutral at zero, red for increases and blue for decreases', () => {
    expect(divergingColor(0, 1)).toBe('rgb(240, 240, 240)')
    const [r1, , b1] = rgb(divergingColor(0.8, 1))
    const [r2, , b2] = rgb(divergingColor(-0.8, 1))
    expect(r1).toBeGreaterThan(b1)
    expect(b2).toBeGreaterThan(r2)
  })
  it('is symmetric: equal magnitudes get equally strong colours', () => {
    const pos = rgb(divergingColor(0.5, 1))
    const neg = rgb(divergingColor(-0.5, 1))
    const dist = (c: number[]) => Math.hypot(c[0] - 240, c[1] - 240, c[2] - 240)
    expect(Math.abs(dist(pos) - dist(neg))).toBeLessThan(25)
  })
  it('clamps beyond the scale limit', () => {
    expect(divergingColor(5, 1)).toBe(divergingColor(1, 1))
    expect(divergingColor(-5, 1)).toBe('rgb(33, 102, 172)')
  })
})

describe('scale limit', () => {
  it('rounds up to readable values', () => {
    expect(niceCeil(0.037)).toBeCloseTo(0.05)
    expect(niceCeil(0.02)).toBeCloseTo(0.02)
    expect(niceCeil(0.21)).toBeCloseTo(0.25)
    expect(niceCeil(0)).toBe(0)
  })
  it('uses only analysed cells and the chosen estimator', () => {
    const cells = makeResponse().cells
    expect(symmetricMax(cells, 'sen')).toBeCloseTo(0.05)
    expect(symmetricMax(cells, 'ols')).toBeCloseTo(0.05)
    expect(symmetricMax([makeCell({ sen_slope: 9, data_status: 'no_variation' })], 'sen')).toBe(0)
  })
})

describe('cell styling', () => {
  const [sig, nonsig, missing] = makeResponse().cells
  it('outlines significant cells on the magnitude layer and colours by slope', () => {
    const s = cellStyle(sig, opts())
    expect(s.weight).toBe(2)
    expect(s.fillColor).toBe(divergingColor(0.028, 0.05))
  })
  it('hiding non-significant cells keeps an outline (they stay in the family)', () => {
    const s = cellStyle(nonsig, opts({ showNonSignificant: false }))
    expect(s.visible).toBe(true)
    expect(s.fillOpacity).toBe(0)
  })
  it('respects the raw vs adjusted basis on the significance layer', () => {
    expect(cellStyle(nonsig, opts({ layer: 'significance', basis: 'raw' })).fillColor).toBe('#1d4ed8')
    expect(cellStyle(nonsig, opts({ layer: 'significance', basis: 'adjusted' })).fillColor).toBe('#cbd5e1')
  })
  it('marks cells without a test and can hide them', () => {
    expect(cellStyle(missing, opts()).dashArray).toBe('4 3')
    expect(cellStyle(missing, opts({ showMissing: false })).visible).toBe(false)
    expect(cellStyle(missing, opts({ layer: 'availability' })).fillColor).toBe('#f97316')
  })
})

describe('exports', () => {
  it('CSV has the required columns in order and one row per cell', () => {
    const csv = spatialCsv(makeResponse())
    const lines = csv.split('\n')
    const header = lines.find((l) => l.startsWith('cell_id'))!
    expect(header.split(',').slice(0, 18)).toEqual([...SPATIAL_CSV_COLUMNS].slice(0, 18))
    expect(lines.filter((l) => /^\d/.test(l))).toHaveLength(3)
    expect(csv).toContain('# DATA MODE: LIVE')
  })
  it('GeoJSON polygons are closed, counter-clockwise and carry statistics', () => {
    const g = spatialGeoJson(makeResponse())
    expect(g.features).toHaveLength(3)
    const ring = g.features[0].geometry.coordinates[0] as number[][] // full (unclipped) cell -> Polygon
    expect(ring[0]).toEqual(ring[ring.length - 1])
    const area2 = ring.slice(0, -1).reduce((s, p, i, a) => s + (p[0] * a[(i + 1) % a.length][1] - a[(i + 1) % a.length][0] * p[1]), 0)
    expect(area2).toBeGreaterThan(0) // positive shoelace area = counter-clockwise
    expect(g.features[0].properties.adjusted_p_value).toBe(0.0004)
    expect(g.features[0].properties.fdr_method).toBe('fdr_bh')
  })
  it('selected-cell series CSV includes trend and regional columns', () => {
    const r = makeResponse()
    const csv = cellSeriesCsv({
      metadata: r.metadata, config: r.config, cell: r.cells[0], statistics: null,
      annual: [{ year: 2001, value: 27, valid_months: 12, used_in_trend: true }, { year: 2002, value: null, valid_months: 3, used_in_trend: false }],
      regional_annual: [{ year: 2001, value: 26.5, used_in_trend: true }],
    })
    expect(csv).toContain('year,cell_annual_mean,valid_months,used_in_trend,ols_trend_value,regional_aggregate_annual_mean')
    expect(csv).toContain(`2001,27,12,true,${-33 + 0.03 * 2001},26.5`) // OLS line: intercept + slope × year
    expect(csv).toContain('2002,,3,false,,')
  })
})
