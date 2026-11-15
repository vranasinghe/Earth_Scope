// Client-side downloads built from the data actually returned by the backend.

import type { AnalysisResponse } from '../types/api'

function csvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const s = String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function download(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function header(r: AnalysisResponse, title: string): string[] {
  const m = r.metadata
  return [
    `# Earth Scope — ${title}`,
    `# DATA MODE: ${m.data_mode}`,
    `# Provider: ${m.provider}`,
    `# Parameter: ${m.parameter} (${m.long_name ?? m.variable_name}); community ${m.community}`,
    `# Sources: ${m.sources.join(', ') || 'n/a'}`,
    `# Units (as reported): ${m.units_raw ?? 'not reported'}`,
    `# Location (requested): lat ${m.latitude_requested}, lon ${m.longitude_requested}; point-based grid-cell value, not a regional average`,
    ...(m.grid_cell
      ? [
          `# Data grid cell (MERRA-2 ${m.grid_cell.lat_step} x ${m.grid_cell.lon_step} deg): centre lat ${m.grid_cell.center_latitude}, lon ${m.grid_cell.center_longitude}; ` +
            `lat ${m.grid_cell.lat_min} to ${m.grid_cell.lat_max}, lon ${m.grid_cell.lon_min} to ${m.grid_cell.lon_max}`,
        ]
      : []),
    `# Period: ${m.start_year}-${m.end_year}; temporal resolution: ${m.temporal_resolution}`,
    `# Retrieved: ${m.retrieved_at}`,
    ...(m.request_url ? [`# Request: ${m.request_url}`] : []),
    `# Documentation: ${m.documentation_url}`,
    '# Missing values are left empty (never zero-filled or interpolated).',
  ]
}

function baseName(r: AnalysisResponse): string {
  const m = r.metadata
  return `earthscope_${m.parameter}_${m.latitude_requested}_${m.longitude_requested}_${m.start_year}-${m.end_year}`
}

export function downloadMonthlyCsv(r: AnalysisResponse) {
  const unit = r.metadata.units_raw ?? ''
  const rows = [
    ...header(r, 'monthly dataset'),
    ['date', 'year', 'month', `value_${r.metadata.parameter}`, 'unit', 'status'].join(','),
    ...r.monthly.map((m) => [m.date, m.year, m.month, m.value, unit, m.status].map(csvCell).join(',')),
  ]
  download(`${baseName(r)}_monthly.csv`, rows.join('\n') + '\n', 'text/csv;charset=utf-8')
}

export function downloadAnnualCsv(r: AnalysisResponse) {
  const unit = r.metadata.units_raw ?? ''
  const rows = [
    ...header(r, 'annual (day-weighted) dataset'),
    `# Years need >= ${r.summary.min_valid_months_per_year} valid months to be used in trend tests.`,
    ['year', `annual_mean_${r.metadata.parameter}`, 'unit', 'valid_months', 'total_months', 'status', 'used_in_trend'].join(','),
    ...r.annual.map((a) =>
      [a.year, a.value, unit, a.valid_months, a.total_months, a.status, a.used_in_trend].map(csvCell).join(','),
    ),
  ]
  download(`${baseName(r)}_annual.csv`, rows.join('\n') + '\n', 'text/csv;charset=utf-8')
}

export function downloadSummaryJson(r: AnalysisResponse) {
  const summary = {
    generated_by: 'Earth Scope',
    exported_at: new Date().toISOString(),
    data_mode: r.metadata.data_mode,
    metadata: r.metadata,
    summary: r.summary,
    statistics: r.statistics,
    analysis_message: r.analysis_message,
    interpretation: r.interpretation,
    warnings: r.warnings,
  }
  download(`${baseName(r)}_analysis.json`, JSON.stringify(summary, null, 2), 'application/json')
}
