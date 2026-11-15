import { createContext, useContext } from 'react'

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'es-theme'

export interface ThemeContextValue {
  /** What the visitor picked (persisted). */
  choice: ThemeChoice
  /** What is applied right now ('system' resolved through prefers-color-scheme). */
  resolved: ResolvedTheme
  setChoice: (c: ThemeChoice) => void
}

export const ThemeContext = createContext<ThemeContextValue>({
  choice: 'system',
  resolved: 'dark',
  setChoice: () => {},
})

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}

export function readStoredChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
  } catch {
    return 'system'
  }
}

export function systemTheme(): ResolvedTheme {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

/**
 * Concrete colours for drawing libraries that cannot read CSS variables
 * (Leaflet canvas renderer, inline SVG fallbacks). Mirrors index.css.
 */
export const MAP_COLORS: Record<ResolvedTheme, { accent: string; surface: string; line: string; subtle: string; warn: string; danger: string; ground: string }> = {
  dark: { accent: '#22d3ee', surface: '#101b2c', line: '#2f445f', subtle: '#8093aa', warn: '#fbbf24', danger: '#f87171', ground: '#0b1422' },
  light: { accent: '#0e7490', surface: '#ffffff', line: '#c3cfdc', subtle: '#5d6f84', warn: '#a35a00', danger: '#b42318', ground: '#f5f7fa' },
}

export function useMapColors() {
  return MAP_COLORS[useTheme().resolved]
}
