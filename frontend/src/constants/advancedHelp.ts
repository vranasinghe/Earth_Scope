// Plain-language explanations shown in the Advanced Statistical Analysis tooltips.
export const HELP = {
  autocorrelation:
    'Autocorrelation means a year tends to resemble the year before it (positive) or to swing the other way (negative). Standard trend tests assume each year is independent; positive autocorrelation makes them too confident.',
  lag1: 'The correlation between each year and the next, after the trend has been removed. Values near 0 suggest independent years; values outside the dashed bound are unusual for independent data.',
  acf: 'The autocorrelation function shows the correlation between years 1, 2, 3… years apart. Bars beyond the dashed lines (±1.96/√n) are larger than expected for independent data — but with short records some can occur by chance.',
  ljungBox:
    'The Ljung–Box test checks several lags at once. A small p-value suggests the years are not independent. A large p-value does not prove independence: short records give the test little power.',
  originalMk:
    'The original Mann-Kendall test checks whether values tend to rise or fall over time (a monotonic trend). It assumes independent years.',
  modifiedMk:
    'The Hamed–Rao modified test keeps the same S statistic but enlarges its variance when the ranked, trend-removed series shows significant positive autocorrelation in the first 3 lags. If none is detected the result equals the original test. Earth Scope never shrinks the variance, because negative autocorrelation estimated from a short record is unreliable and would make the test over-confident.',
  effectiveN:
    'Positive autocorrelation means consecutive years carry overlapping information, so the record behaves like fewer independent years. This is that equivalent number.',
  senCi:
    'Sen’s slope is the median of the slopes between every pair of years. Its 95% interval comes from ranking those pairwise slopes (Sen 1968), not from the regression, and it assumes independent years.',
  hac: 'Newey–West (HAC) standard errors keep the same regression line but estimate its uncertainty in a way that allows for autocorrelation and unequal variance. They are approximate for short records.',
  ols: 'Ordinary least squares fits a straight line. Its p-value and interval assume independent, equally variable, normally distributed residuals.',
  yueWang:
    'A second, simpler correction (Yue & Wang 2004) using lag-1 autocorrelation only, applied whether or not it is significant. Shown only as a sensitivity check; it is not used for the conclusions.',
  canonical:
    'The published Hamed & Rao (1998) method applies the estimated correction as-is, including variance reductions from negative autocorrelation. It is shown for transparency; Earth Scope’s decision column uses the conservative variant that never reduces the variance.',
  robust:
    'Combines the regression (counted as significant only if both the ordinary and the Newey–West p-values are below 0.05) with the Hamed–Rao modified Mann-Kendall test, using the same rules as the standard evidence card. It is designed never to be more significant than the standard evidence.',
} as const
