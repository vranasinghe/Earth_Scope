import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { makeResponse } from '../../test/spatialFixture'
import { SpatialTrendControls } from './SpatialTrendControls'
import { SpatialTrendLegend } from './SpatialTrendLegend'
import { SpatialTrendSummary } from './SpatialTrendSummary'

const r = makeResponse()
const baseControls = {
  variableName: 'Air Temperature', parameter: 'T2M', startYear: 2001, endYear: 2020, config: r.config,
  settings: { method: 'mann_kendall' as const, correction: 'fdr_bh' as const, alpha: 0.05 },
  onSettings: vi.fn(), layer: 'magnitude' as const, onLayer: vi.fn(), estimator: 'sen' as const, onEstimator: vi.fn(),
  basis: 'adjusted' as const, onBasis: vi.fn(),
  toggles: { showGrid: true, showBoundary: true, showMissing: true, showNonSignificant: true }, onToggles: vi.fn(),
  trendLayersAvailable: true, busy: false,
}

describe('SpatialTrendControls', () => {
  it('changes test, correction and threshold through onSettings', () => {
    const onSettings = vi.fn()
    render(<SpatialTrendControls {...baseControls} onSettings={onSettings} />)
    fireEvent.change(screen.getByRole('combobox', { name: /^Statistical test/ }), { target: { value: 'hamed_rao_canonical' } })
    expect(onSettings).toHaveBeenLastCalledWith({ method: 'hamed_rao_canonical', correction: 'fdr_bh', alpha: 0.05 })
    fireEvent.change(screen.getByRole('combobox', { name: /^Multiple-testing correction/ }), { target: { value: 'fdr_by' } })
    expect(onSettings).toHaveBeenLastCalledWith({ method: 'mann_kendall', correction: 'fdr_by', alpha: 0.05 })
    fireEvent.change(screen.getByRole('combobox', { name: /^Significance threshold/ }), { target: { value: '0.1' } })
    expect(onSettings).toHaveBeenLastCalledWith({ method: 'mann_kendall', correction: 'fdr_bh', alpha: 0.1 })
  })
  it('switches layers and shows the active configuration', () => {
    const onLayer = vi.fn()
    render(<SpatialTrendControls {...baseControls} onLayer={onLayer} />)
    fireEvent.click(screen.getByRole('radio', { name: 'Statistical significance' }))
    expect(onLayer).toHaveBeenCalledWith('significance')
    expect(screen.getByText(/2 cells in the correction family/)).toBeInTheDocument()
  })
  it('disables trend layers when no cell could be tested', () => {
    render(<SpatialTrendControls {...baseControls} trendLayersAvailable={false} layer="availability" />)
    expect(screen.getByRole('radio', { name: 'Trend magnitude' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Data availability' })).toBeEnabled()
  })
  it('offers raw vs adjusted classification only with a correction', () => {
    const { rerender } = render(<SpatialTrendControls {...baseControls} layer="significance" />)
    expect(screen.getByRole('radio', { name: /FDR-adjusted/ })).toBeInTheDocument()
    rerender(<SpatialTrendControls {...baseControls} layer="significance" settings={{ ...baseControls.settings, correction: 'none' }} />)
    expect(screen.queryByRole('radio', { name: /FDR-adjusted/ })).toBeNull()
  })
})

describe('SpatialTrendLegend', () => {
  const legend = { maxAbs: 0.05, rateUnit: '°C/year', variableName: 'Air Temperature', estimator: 'sen' as const, basis: 'adjusted' as const,
    correction: 'fdr_bh' as const, alpha: 0.05, showNonSignificant: true, showMissing: true }
  it('magnitude legend shows a symmetric numeric scale and the significance caveat', () => {
    render(<SpatialTrendLegend layer="magnitude" {...legend} />)
    // formatSigned(±0.05): the negative end has the plain minus, the positive end a '+'.
    const ends = screen.getAllByText(/^[+-]?0\.05/).map((e) => e.textContent)
    expect(ends).toHaveLength(2)
    expect(ends[0]!.startsWith('-')).toBe(true)
    expect(ends[1]!.startsWith('+')).toBe(true)
    expect(ends[0]!.slice(1)).toBe(ends[1]!.slice(1)) // symmetric
    expect(screen.getByText(/Colour shows the slope only, not significance/)).toBeInTheDocument()
  })
  it('significance legend names all categories and the basis', () => {
    render(<SpatialTrendLegend layer="significance" {...legend} />)
    for (const t of ['Significant increase', 'Significant decrease', 'Not statistically significant', 'Insufficient data']) {
      expect(screen.getByText(t)).toBeInTheDocument()
    }
    expect(screen.getByText(/Benjamini–Hochberg q ≤ 0.05/)).toBeInTheDocument()
    expect(screen.getByText(/not that the trend is exactly zero/)).toBeInTheDocument()
  })
  it('explains hidden non-significant cells', () => {
    render(<SpatialTrendLegend layer="significance" {...legend} showNonSignificant={false} />)
    expect(screen.getByText(/still in the correction family/)).toBeInTheDocument()
  })
})

describe('SpatialTrendSummary', () => {
  it('shows counts with separate cell and area percentages', () => {
    render(<SpatialTrendSummary summary={r.summary} config={r.config} regional={r.regional_aggregate} rateUnit="°C/year" />)
    expect(screen.getByText('Significant increase')).toBeInTheDocument()
    expect(screen.getAllByText(/50% of tested cells · 50% of tested area/)).toHaveLength(2)
    expect(screen.getByText('1 cells')).toBeInTheDocument() // FDR discoveries
    expect(screen.getByText(/regional slope and the average of cell slopes are different quantities/)).toBeInTheDocument()
  })
})
