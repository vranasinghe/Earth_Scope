import { Check, PenLine, RotateCcw, Trash2, Undo2, Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import type { AreaGeometry } from '../../types/area'
import { countVertices, editableVertices, MAX_UPLOAD_BYTES, parseGeoJSONText } from '../../utils/polygon'
import type { LatLng } from '../../utils/polygon'

interface Props {
  vertices: LatLng[]
  onVertices: (v: LatLng[]) => void
  drawing: boolean
  onDrawing: (d: boolean) => void
  uploaded: AreaGeometry | null
  onUploaded: (g: AreaGeometry | null) => void
  name: string
  onName: (n: string) => void
  errors: string[]
  onFinish: () => void
}

export function PolygonPanel(p: Props) {
  const file = useRef<HTMLInputElement>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const hasShape = p.vertices.length > 0 || p.uploaded !== null

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    setUploadError(null)
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    if (f.size > MAX_UPLOAD_BYTES) {
      setUploadError(`The file is larger than ${MAX_UPLOAD_BYTES / 1_000_000} MB.`)
      return
    }
    try {
      const g = parseGeoJSONText(await f.text())
      const editable = editableVertices(g)
      p.onDrawing(false)
      if (editable) {
        p.onUploaded(null)
        p.onVertices(editable)
      } else {
        p.onVertices([])
        p.onUploaded(g)
      }
      if (!p.name || p.name === 'Custom polygon') p.onName(f.name.replace(/\.(geo)?json$/i, '').slice(0, 80) || 'Uploaded area')
    } catch (err) {
      setUploadError((err as Error).message)
    }
  }

  const reset = () => {
    p.onVertices([])
    p.onUploaded(null)
    p.onDrawing(false)
    setUploadError(null)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {!p.drawing ? (
          <button
            type="button"
            className="btn-primary"
            onClick={() => {
              p.onUploaded(null)
              p.onVertices([])
              p.onDrawing(true)
            }}
          >
            <PenLine className="size-4" aria-hidden /> {hasShape ? 'Draw a new polygon' : 'Draw polygon'}
          </button>
        ) : (
          <>
            <button type="button" className="btn-primary" disabled={p.vertices.length < 3} onClick={p.onFinish}>
              <Check className="size-4" aria-hidden /> Finish polygon
            </button>
            <button type="button" className="btn-secondary" disabled={p.vertices.length === 0} onClick={() => p.onVertices(p.vertices.slice(0, -1))}>
              <Undo2 className="size-4" aria-hidden /> Undo vertex
            </button>
            <button type="button" className="btn-ghost" onClick={reset}>
              <X className="size-4" aria-hidden /> Cancel
            </button>
          </>
        )}
        {hasShape && !p.drawing && (
          <>
            <button type="button" className="btn-ghost" onClick={reset}>
              <Trash2 className="size-4" aria-hidden /> Delete polygon
            </button>
          </>
        )}
      </div>
      {p.drawing ? (
        <p className="text-xs text-accent" role="status">
          Click on the map to add vertices ({p.vertices.length} so far). Click the first vertex, double-click, or press “Finish polygon” to close it.
        </p>
      ) : p.vertices.length >= 3 ? (
        <p className="text-xs text-fg-muted">
          Edit: drag a vertex to move it · click a small round handle on an edge to add a vertex · right-click (or Alt-click) a vertex to delete it.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className="btn-secondary" onClick={() => file.current?.click()}>
          <Upload className="size-4" aria-hidden /> Upload GeoJSON
        </button>
        {hasShape && (
          <button type="button" className="btn-ghost" onClick={reset}>
            <RotateCcw className="size-4" aria-hidden /> Reset selection
          </button>
        )}
        <input ref={file} type="file" accept=".geojson,.json,application/geo+json,application/json" className="sr-only" onChange={onFile} aria-label="Upload a GeoJSON polygon file" />
      </div>
      <p className="text-[11px] text-fg-subtle">
        Polygon or MultiPolygon (Feature / FeatureCollection accepted), WGS84 longitude/latitude, ≤ {MAX_UPLOAD_BYTES / 1_000_000} MB and ≤ 5,000 vertices.
        The file is read in your browser and validated again by the server; nothing is downloaded from links inside it.
      </p>
      {uploadError && <p className="text-sm text-danger" role="alert">{uploadError}</p>}
      {p.uploaded && (
        <p className="text-xs text-fg-muted">
          Uploaded {p.uploaded.type} with {countVertices(p.uploaded).toLocaleString()} vertices (shown read-only because it has several parts or holes).
        </p>
      )}

      <div>
        <label htmlFor="poly-name" className="label">
          Name (for results and exports)
        </label>
        <input id="poly-name" className="input font-sans" maxLength={80} value={p.name} onChange={(e) => p.onName(e.target.value)} />
      </div>
      {p.errors.length > 0 && !p.drawing && (
        <ul className="space-y-1 text-sm text-danger" role="alert">
          {p.errors.map((e) => (
            <li key={e}>• {e}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
