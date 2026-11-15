import { SPATIAL_HELP } from '../../constants/spatialHelp'

const ITEMS: [string, string][] = [
  ['What is a spatial trend?', SPATIAL_HELP.spatialTrend],
  ['What is a grid cell?', SPATIAL_HELP.gridCell],
  ['What is a slope?', SPATIAL_HELP.slope],
  ['What is a significant trend?', SPATIAL_HELP.significant],
  ['What is a p-value?', SPATIAL_HELP.pValue],
  ['What is FDR?', SPATIAL_HELP.fdr],
  ['What is a q-value (adjusted p-value)?', SPATIAL_HELP.qValue],
  ['Why can neighbouring cells be dependent?', SPATIAL_HELP.dependence],
  ['Why can regional averages hide opposing trends?', SPATIAL_HELP.hiddenTrends],
  ['Does a significant trend prove the cause?', SPATIAL_HELP.causation],
  ['What does “near zero” mean on the direction layer?', SPATIAL_HELP.nearZero],
]

/** Short explanations for students — collapsible so the map stays the focus. */
export function SpatialStatisticalHelp() {
  return (
    <details className="card card-pad group">
      <summary className="cursor-pointer font-semibold text-fg">Understanding the spatial trend map</summary>
      <dl className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
        {ITEMS.map(([q, a]) => (
          <div key={q}>
            <dt className="font-semibold text-fg">{q}</dt>
            <dd className="mt-1 text-fg-muted">{a}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
