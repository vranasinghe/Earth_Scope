import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../services/api'
import type { AreaPreviewResponse } from '../../types/area'
import { AreaPreviewCard } from './AreaPreviewCard'
import { CountrySearch } from './CountrySearch'
import { PolygonPanel } from './PolygonPanel'

const COUNTRIES = [
  { iso3: 'IND', name: 'India', source: 'Natural Earth', status: 'sovereign country' },
  { iso3: 'KEN', name: 'Kenya', source: 'geoBoundaries', status: 'country' },
  { iso3: 'LKA', name: 'Sri Lanka', source: 'geoBoundaries', status: 'country' },
]

describe('CountrySearch', () => {
  it('filters by name and selects with the mouse', () => {
    const onSelect = vi.fn()
    render(<CountrySearch countries={COUNTRIES} selected={null} onSelect={onSelect} />)
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'lan' } })
    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.click(screen.getByRole('option', { name: /Sri Lanka/ }))
    expect(onSelect).toHaveBeenCalledWith('LKA')
  })
  it('matches ISO codes and supports keyboard selection', () => {
    const onSelect = vi.fn()
    render(<CountrySearch countries={COUNTRIES} selected={null} onSelect={onSelect} />)
    const input = screen.getByRole('combobox')
    fireEvent.change(input, { target: { value: 'ken' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onSelect).toHaveBeenCalledWith('KEN')
  })
  it('labels the Natural Earth fallback and reports no matches', () => {
    render(<CountrySearch countries={COUNTRIES} selected="IND" onSelect={() => {}} />)
    const input = screen.getByRole('combobox')
    expect(input).toHaveAttribute('placeholder', 'India (IND)')
    fireEvent.focus(input)
    expect(screen.getByRole('option', { name: /India/ })).toHaveTextContent('NE')
    fireEvent.change(input, { target: { value: 'atlantis' } })
    expect(screen.getByText(/No country matches/)).toBeInTheDocument()
  })
})

const preview = (available: boolean): AreaPreviewResponse => ({
  area: {
    kind: 'country', name: 'Sri Lanka', iso3: 'LKA', geometry_id: 'geom-1', geometry: { type: 'Polygon', coordinates: [[[80, 6], [81, 6], [81, 7], [80, 6]]] },
    bbox: { lat_min: 5.9, lat_max: 9.8, lon_min: 79.5, lon_max: 81.9 }, area_km2: 66360, geodesic_area_km2: 66079, n_components: 18, n_vertices: 2402,
    boundary: { source: 'geoBoundaries', dataset: 'gbOpen', version: 'gbOpen commit 9469f09', boundary_id: 'LKA-ADM0-1', year_represented: '2017',
      license: 'ODbL 1.0', license_source: null, upstream_source: 'OSM', build_date: null, attribution: 'geoBoundaries', status: 'country', reported_area_km2: 66069, geometry_url: null },
    notes: [],
  },
  preflight: {
    valid: true, available, reasons: available ? [] : ['It intersects 4089 NASA grid cells; the limit is 3000.'],
    suggestions: available ? [] : ['Draw a custom polygon around a smaller part of the country.'], n_cells: available ? 30 : 4089, n_tiles: available ? 1 : 47,
    n_months: 300, n_values: 9000, estimated_seconds: 3, estimated_spatial_seconds: 0.2, estimated_memory_mb: 12, mean_cell_overlap_km2: 2200,
    small_area_warning: null, tiles: [], limits: {}, grid: 'MERRA-2',
  },
  variable: 'air_temperature', start_year: 2001, end_year: 2025,
})

describe('AreaPreviewCard', () => {
  it('shows area, boundary provenance, cells and requests when available', () => {
    render(<AreaPreviewCard data={preview(true)} loading={false} error={null} onRetry={() => {}} emptyText="" />)
    expect(screen.getByText('Ready to analyse')).toBeInTheDocument()
    expect(screen.getByText('Sri Lanka (LKA)')).toBeInTheDocument()
    expect(screen.getByText(/geoBoundaries · gbOpen commit 9469f09/)).toBeInTheDocument()
    expect(screen.getByText('ODbL 1.0')).toBeInTheDocument()
    expect(screen.getByText(/30 \(0.5° × 0.625°\)/)).toBeInTheDocument()
  })
  it('explains budget refusals and offers smaller selections', () => {
    render(<AreaPreviewCard data={preview(false)} loading={false} error={null} onRetry={() => {}} emptyText="" />)
    expect(screen.getByRole('alert')).toHaveTextContent('This region exceeds the instant (synchronous) analysis limit.')
    expect(screen.getByText(/limit is 3000/)).toBeInTheDocument()
    expect(screen.getByText(/smaller part of the country/)).toBeInTheDocument()
  })
  it('shows geometry errors from the server', () => {
    const err = new ApiError(422, { error: 'INVALID_GEOMETRY', message: 'The polygon is not valid.', details: ['Self-intersection[1 1]'] }, '')
    render(<AreaPreviewCard data={null} loading={false} error={err} onRetry={() => {}} emptyText="" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Self-intersection')
  })
})

describe('PolygonPanel', () => {
  const base = {
    vertices: [], onVertices: vi.fn(), drawing: false, onDrawing: vi.fn(), uploaded: null, onUploaded: vi.fn(),
    name: 'Custom polygon', onName: vi.fn(), errors: [], onFinish: vi.fn(),
  }
  it('starts drawing and offers finish / undo while drawing', () => {
    const onDrawing = vi.fn()
    const { rerender } = render(<PolygonPanel {...base} onDrawing={onDrawing} />)
    fireEvent.click(screen.getByRole('button', { name: /Draw polygon/ }))
    expect(onDrawing).toHaveBeenCalledWith(true)
    rerender(<PolygonPanel {...base} drawing vertices={[[6, 80], [6, 81]]} />)
    expect(screen.getByRole('button', { name: /Finish polygon/ })).toBeDisabled() // < 3 vertices
    expect(screen.getByText(/2 so far/)).toBeInTheDocument()
  })
  it('deletes the polygon and shows validation errors', () => {
    const onVertices = vi.fn()
    render(<PolygonPanel {...base} vertices={[[6, 80], [6, 81], [7, 81]]} onVertices={onVertices} errors={['Edges cross each other.']} />)
    fireEvent.click(screen.getByRole('button', { name: /Delete polygon/ }))
    expect(onVertices).toHaveBeenCalledWith([])
    expect(screen.getByRole('alert')).toHaveTextContent('Edges cross each other.')
  })
  it('loads an uploaded GeoJSON polygon as editable vertices and rejects bad files', async () => {
    const onVertices = vi.fn()
    const onName = vi.fn()
    render(<PolygonPanel {...base} onVertices={onVertices} onName={onName} />)
    const input = screen.getByLabelText('Upload a GeoJSON polygon file')
    const good = new File([JSON.stringify({ type: 'Polygon', coordinates: [[[80, 6], [81, 6], [81, 7], [80, 6]]] })], 'farm.geojson')
    fireEvent.change(input, { target: { files: [good] } })
    await waitFor(() => expect(onVertices).toHaveBeenCalledWith([[6, 80], [6, 81], [7, 81]]))
    expect(onName).toHaveBeenCalledWith('farm')
    const bad = new File(['{"type":"LineString","coordinates":[[0,0],[1,1]]}'], 'line.geojson')
    fireEvent.change(input, { target: { files: [bad] } })
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/Unsupported geometry type/))
  })
})
