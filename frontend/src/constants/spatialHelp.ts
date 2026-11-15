// Plain-language explanations for the Spatial Trend Explorer tooltips.
export const SPATIAL_HELP = {
  spatialTrend:
    'A spatial trend map shows the trend of every grid cell separately, so you can see where values rose, fell or stayed roughly the same — instead of one number for the whole region.',
  gridCell:
    'NASA POWER provides values on a regular grid. Each rectangle here is one MERRA-2 cell of 0.5° latitude × 0.625° longitude (about 55 × 69 km near the equator). Its value is a modelled average for the cell, not a measurement from a weather station.',
  slope:
    'The slope is the average change per year. Sen’s slope is the median of the changes between every pair of years (robust to unusual years); the OLS slope is the straight-line fit. The colour shows the size of the change, not whether it is statistically significant.',
  significant:
    'A cell is marked significant when its trend test gives strong enough evidence that the values were not just fluctuating randomly. It does not mean the change is large or important, and non-significant does not mean “no change” — only that the evidence is not strong enough under this test.',
  pValue:
    'The p-value is the probability of seeing a trend at least this strong if there were really no trend. Small values (below the threshold, e.g. 0.05) count as evidence of a trend.',
  fdr:
    'Testing many cells at once makes some look significant by chance: with 100 trendless cells and α = 0.05 you expect about 5 false “trends”. A false discovery rate (FDR) correction keeps the expected share of false discoveries among the significant cells at or below α, under its assumptions. It does not guarantee that any single highlighted cell is a true trend.',
  qValue:
    'The adjusted p-value (often called a q-value) is a cell’s p-value after the FDR correction. A cell is a discovery when its adjusted p-value is at most the threshold.',
  dependence:
    'Neighbouring cells share weather systems and the model’s smoothing, so their values and trends are correlated. Benjamini–Hochberg is proven for independent or positively correlated tests; Benjamini–Yekutieli is valid under any dependence but finds fewer significant cells.',
  hiddenTrends:
    'A regional average combines all cells. If some cells warm and others cool, the average can show little or no trend even though strong local changes exist. Compare the map with the single regional trend.',
  causation:
    'A significant trend describes how the values changed. It does not tell you why — land use, climate variability, model changes or other factors could all play a role.',
  method:
    'The test whose p-values define the significance map. Original Mann-Kendall assumes independent years. Hamed–Rao and Yue–Wang adjust for autocorrelation; “canonical” means the published method, while Earth Scope’s conservative variant never lets the correction make a cell more significant.',
  nearZero:
    'Display rule only: a slope is drawn as “near zero” when the change it implies over the whole period is less than 10% of the cell’s usual year-to-year variation.',
} as const
