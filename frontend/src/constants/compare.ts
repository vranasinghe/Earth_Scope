// Comparison series styling. Colours validated for colour-vision-deficiency
// separation and contrast on the dark chart surface (#0f1b2d); each series also
// has its own dash pattern so identity never relies on colour alone.
export const COMPARE_SERIES = [
  { color: '#3b82f6', dash: undefined, dashLabel: 'solid' },
  { color: '#d07a08', dash: '7 4', dashLabel: 'dashed' },
  { color: '#2fa37a', dash: '2 3', dashLabel: 'dotted' },
] as const
