export interface Concept {
  id: string
  title: string
  body: string
  example?: string
}

export const CONCEPTS: Concept[] = [
  {
    id: 'time-series',
    title: 'What is a time series?',
    body: 'A time series is a list of measurements of the same thing, taken at regular times — for example, the average temperature of every month since 2001. Putting them in order lets us see how something changes over time.',
    example: 'Earth Scope retrieves one value per month from NASA POWER, then averages each year.',
  },
  {
    id: 'trend',
    title: 'What is a trend?',
    body: 'A trend is the long-term direction of a time series, after looking past the short-term ups and downs such as seasons or an unusually hot year.',
  },
  {
    id: 'positive',
    title: 'What is a positive trend?',
    body: 'A positive (increasing) trend means values tend to get larger over time. For temperature that means warming; for soil wetness it means wetter soil.',
  },
  {
    id: 'negative',
    title: 'What is a negative trend?',
    body: 'A negative (decreasing) trend means values tend to get smaller over time — for example, relative humidity falling a little each year.',
  },
  {
    id: 'regression',
    title: 'What is linear regression?',
    body: 'Linear regression draws the single straight line that best fits the data (it minimises the squared distances between the points and the line). The slope of that line is the average rate of change — for example, “0.02 °C per year”. R² tells you how much of the year-to-year variation the line explains (0 = none, 1 = all).',
  },
  {
    id: 'mann-kendall',
    title: 'What is the Mann-Kendall test?',
    body: 'The Mann-Kendall test compares every pair of years and counts how often the later year is higher or lower than the earlier one. If one direction clearly dominates, there is a monotonic (consistently upward or downward) trend. It does not require the change to follow a straight line and is not strongly affected by outliers. Sen’s slope, the median of all pairwise slopes, gives a matching robust rate of change.',
  },
  {
    id: 'p-value',
    title: 'What does a p-value mean?',
    body: 'Imagine there were really no trend at all. The p-value is the probability of seeing a trend at least as strong as the one observed purely by chance in that situation. A small p-value (e.g. 0.01) means such a pattern would be unusual if there were no real trend.',
    example: 'A p-value is NOT the probability that the trend is real.',
  },
  {
    id: 'significance',
    title: 'What does statistical significance mean?',
    body: 'Before testing we choose a threshold, α = 0.05. If the p-value is below α we call the trend “statistically significant”: the data provide reasonable evidence that the change is not just random variation. “Significant” does not mean large or important — a tiny change can be significant, and a large-looking change in a short, noisy record may not be.',
  },
  {
    id: 'confidence-interval',
    title: 'What is a confidence interval?',
    body: 'A 95% confidence interval is a range of plausible values for the true rate of change. If it lies entirely above zero, the data point to an increase; if it includes zero, “no change” is still plausible.',
  },
  {
    id: 'causation',
    title: 'Why is a trend not proof of causation?',
    body: 'A trend tells us that something changed, not why. A warming trend at one location could relate to global climate change, local land-use change, natural cycles such as El Niño, or how the model represents that place. Finding the cause requires additional evidence and different methods.',
  },
]
