import { Download } from 'lucide-react'
import type { AnalysisResponse } from '../../types/api'
import { downloadAnnualCsv, downloadMonthlyCsv, downloadSummaryJson } from '../../utils/export'

export function ExportPanel({ result }: { result: AnalysisResponse }) {
  const items = [
    { label: 'Monthly data', meta: `CSV · ${result.monthly.length} rows`, run: () => downloadMonthlyCsv(result) },
    { label: 'Annual means', meta: `CSV · ${result.annual.length} rows`, run: () => downloadAnnualCsv(result) },
    { label: 'Summary', meta: 'JSON · statistics + metadata', run: () => downloadSummaryJson(result) },
  ]
  return (
    <div>
      <div className="flex flex-wrap gap-3">
        {items.map((it) => (
          <button key={it.label} type="button" className="btn-secondary" onClick={it.run}>
            <Download className="size-4 text-fg-subtle" aria-hidden />
            {it.label}
            <span className="font-normal text-fg-subtle">{it.meta}</span>
          </button>
        ))}
      </div>
      <p className="mt-3 text-sm text-fg-subtle">
        Exactly the data and results shown here, with source metadata in the file header.
      </p>
    </div>
  )
}
