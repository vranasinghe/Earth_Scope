import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeSwitch } from '../components/layout/ThemeSwitch'
import { THEME_STORAGE_KEY, readStoredChoice } from './theme'
import { ThemeProvider } from './ThemeProvider'

let systemLight = false
let listeners: ((e: { matches: boolean }) => void)[] = []

beforeEach(() => {
  systemLight = false
  listeners = []
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('light') ? systemLight : !systemLight,
    media: q,
    addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.push(fn),
    removeEventListener: () => {},
  }))
})
afterEach(() => vi.unstubAllGlobals())

const mount = () =>
  render(
    <ThemeProvider>
      <ThemeSwitch />
    </ThemeProvider>,
  )

describe('theme switch', () => {
  it('follows the system theme by default', () => {
    systemLight = true
    mount()
    expect(screen.getByRole('radio', { name: 'Match system theme' })).toHaveAttribute('aria-checked', 'true')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('applies a chosen theme immediately and persists it', () => {
    mount()
    fireEvent.click(screen.getByRole('radio', { name: 'Light theme' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
    fireEvent.click(screen.getByRole('radio', { name: 'Dark theme' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(readStoredChoice()).toBe('dark')
  })

  it('restores the saved choice on the next visit', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'light')
    mount()
    expect(screen.getByRole('radio', { name: 'Light theme' })).toHaveAttribute('aria-checked', 'true')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('tracks live system changes only while set to system', () => {
    mount()
    expect(document.documentElement.dataset.theme).toBe('dark')
    act(() => listeners.forEach((fn) => fn({ matches: true })))
    expect(document.documentElement.dataset.theme).toBe('light')
    fireEvent.click(screen.getByRole('radio', { name: 'Dark theme' }))
    act(() => listeners.forEach((fn) => fn({ matches: true })))
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('is a keyboard-operable radio group', () => {
    mount()
    const group = screen.getByRole('radiogroup', { name: 'Colour theme' })
    fireEvent.keyDown(group, { key: 'ArrowRight' })
    expect(screen.getByRole('radio', { name: 'Dark theme' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.keyDown(group, { key: 'ArrowRight' })
    expect(screen.getByRole('radio', { name: 'Light theme' })).toHaveAttribute('aria-checked', 'true')
  })
})
