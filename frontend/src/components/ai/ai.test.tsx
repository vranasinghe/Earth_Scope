import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAiPageContext, useAiSpatialContext } from '../../context/aiChatContext'
import { AiChatProvider } from '../../context/AiChatProvider'
import type { AiPageContext, AiSpatialReference } from '../../types/ai'
import { learnContext, pointContext, quickActionsFor, regionalContext } from '../../utils/buildAiContext'
import { renderSafeMarkdown } from '../../utils/safeMarkdown'
import { AiChat } from './AiChat'

const STATUS_OK = {
  enabled: true, configured: true, available: true, reason: 'ok', model: 'auto', message: 'AI Assistant is ready.',
  limits: { max_message_chars: 2000, max_history_messages: 20, requests_per_minute: 8, requests_per_hour: 60 },
  privacy_notice: 'Messages are sent to Google Gemini.',
}
const STATUS_OFF = { ...STATUS_OK, configured: false, available: false, reason: 'missing_api_key', model: null, message: 'AI Assistant is not configured yet.' }

const POINT = pointContext({ variable: 'T2M', latitude: 6.93, longitude: 79.85, startYear: 2001, endYear: 2025 }, 'Colombo', 'Air Temperature')
const OTHER_POINT = pointContext({ variable: 'T2M', latitude: 51.5, longitude: -0.12, startYear: 2001, endYear: 2025 }, 'London', 'Air Temperature')
const REGION = regionalContext(
  { variable: 'T2M', bbox: { lat_min: 6, lat_max: 9.5, lon_min: 79.5, lon_max: 82 }, startYear: 2001, endYear: 2025, coverageThreshold: 0.8 },
  'Air Temperature for the selected rectangle, 2001–2025',
)

type Reply = { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>
let status: unknown
let replies: Reply[]
let posts: Record<string, unknown>[]

function respond(r: { status?: number; body: unknown }) {
  return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  status = STATUS_OK
  replies = []
  posts = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/ai/status')) return respond({ body: status })
      if (url.endsWith('/api/ai/chat')) {
        posts.push(JSON.parse(String(init?.body)))
        const next = replies.shift() ?? { body: { reply: 'An answer.', context_id: 'abc', context_label: 'x', has_results: true, model: 'm', usage: null, generated: true } }
        return respond(await next)
      }
      return respond({ status: 404, body: { error: 'NOT_FOUND', message: 'nope' } })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Page({ ctx, spatial }: { ctx: AiPageContext | null; spatial?: AiSpatialReference | null }) {
  useAiPageContext(ctx)
  useAiSpatialContext(spatial ?? null)
  return null
}

function Harness({ initial = POINT, spatial = null }: { initial?: AiPageContext | null; spatial?: AiSpatialReference | null }) {
  const [ctx, setCtx] = useState<AiPageContext | null>(initial)
  return (
    <MemoryRouter initialEntries={['/results']}>
      <AiChatProvider>
        <Page ctx={ctx} spatial={spatial} />
        <button type="button" onClick={() => setCtx(OTHER_POINT)}>switch analysis</button>
        <AiChat />
      </AiChatProvider>
    </MemoryRouter>
  )
}

const open = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'Open Earth Scope AI assistant' }))
  await screen.findByRole('dialog', { name: 'Earth Scope AI' })
  await waitFor(() => expect(screen.getByLabelText('Ask about this analysis')).not.toBeDisabled())
}
const typeAndSend = (text: string) => {
  const box = screen.getByLabelText('Ask about this analysis')
  fireEvent.change(box, { target: { value: text } })
  fireEvent.keyDown(box, { key: 'Enter' })
}

describe('Earth Scope AI chat', () => {
  it('shows the launcher with an "Ask me" label and opens the chat with the welcome message', async () => {
    render(<Harness />)
    expect(screen.getByText('Ask me')).toBeInTheDocument()
    await open()
    expect(screen.getByText(/I'm your Earth Scope AI assistant/)).toBeInTheDocument()
    expect(screen.getByText('Understand your analysis · Air Temperature at Colombo, 2001–2025')).toBeInTheDocument()
  })

  it('sends a message with the page reference (no numbers) and shows the reply', async () => {
    render(<Harness />)
    await open()
    typeAndSend('Explain the trend')
    expect(await screen.findByText('An answer.')).toBeInTheDocument()
    expect(posts[0]).toMatchObject({ message: 'Explain the trend', action: 'ask', page_type: 'point_results', history: [] })
    expect(posts[0].reference).toEqual({ variable: 'T2M', latitude: 6.93, longitude: 79.85, start_year: 2001, end_year: 2025, place: 'Colombo' })
  })

  it('keeps the conversation when minimized and restores it on reopen; sends history for follow-ups', async () => {
    render(<Harness />)
    await open()
    typeAndSend('Summarize please')
    await screen.findByText('An answer.')
    fireEvent.click(screen.getByRole('button', { name: 'Minimize (keeps the conversation)' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await open()
    expect(screen.getByText('Summarize please')).toBeInTheDocument()
    typeAndSend('What does the p-value mean?')
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].history).toEqual([
      { role: 'user', content: 'Summarize please' },
      { role: 'assistant', content: 'An answer.' },
    ])
  })

  it('quick action "Summarize this analysis" sends the summarize action', async () => {
    render(<Harness />)
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Summarize this analysis' }))
    await screen.findByText('An answer.')
    expect(posts[0]).toMatchObject({ action: 'summarize', message: '', page_type: 'point_results' })
    expect(within(screen.getByRole('log')).getByText('Summarize this analysis')).toBeInTheDocument()
  })

  it('"New conversation" clears history; "End conversation" clears and closes', async () => {
    render(<Harness />)
    await open()
    typeAndSend('first question')
    await screen.findByText('An answer.')
    fireEvent.click(screen.getByRole('button', { name: 'New conversation (clears the chat)' }))
    expect(screen.queryByText('first question')).not.toBeInTheDocument()
    expect(screen.getByText(/I'm your Earth Scope AI assistant/)).toBeInTheDocument()
    typeAndSend('second question')
    await screen.findByText('An answer.')
    expect(posts[1].history).toEqual([])
    fireEvent.click(screen.getByRole('button', { name: 'End conversation (clears the chat and closes)' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await open()
    expect(screen.queryByText('second question')).not.toBeInTheDocument()
  })

  it('never writes the conversation to browser storage, so a reload starts empty', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    const { unmount } = render(<Harness />)
    await open()
    typeAndSend('secret farm question')
    await screen.findByText('An answer.')
    expect(setItem.mock.calls.some((c) => String(c[1]).includes('secret farm'))).toBe(false)
    expect(document.cookie).not.toContain('secret')
    unmount() // a page reload remounts the app from scratch
    render(<Harness />)
    await open()
    expect(screen.queryByText('secret farm question')).not.toBeInTheDocument()
    setItem.mockRestore()
  })

  it('shows a thinking indicator and blocks duplicate submissions while a reply is pending', async () => {
    let release: (v: { body: unknown }) => void = () => {}
    replies.push(new Promise((r) => (release = r)))
    render(<Harness />)
    await open()
    typeAndSend('one')
    expect(await screen.findByText('Earth Scope AI is thinking…')).toBeInTheDocument()
    typeAndSend('two')
    fireEvent.click(screen.getByRole('button', { name: 'Summarize this analysis' }))
    expect(posts).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    await act(async () => release({ body: { reply: 'done', context_id: null, context_label: null, has_results: true, model: null, usage: null, generated: true } }))
    expect(await screen.findByText('done')).toBeInTheDocument()
    expect(screen.queryByText('Earth Scope AI is thinking…')).not.toBeInTheDocument()
  })

  it('shows a friendly error and retries without inventing an answer', async () => {
    replies.push({ status: 503, body: { error: 'AI_UNAVAILABLE', message: 'AI Assistant is temporarily unavailable. Please try again.', details: [], retryable: true } })
    render(<Harness />)
    await open()
    typeAndSend('hello')
    expect(await screen.findByRole('alert')).toHaveTextContent('AI Assistant is temporarily unavailable. Please try again.')
    expect(screen.queryByText('An answer.')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Try again/ }))
    expect(await screen.findByText('An answer.')).toBeInTheDocument()
    expect(posts).toHaveLength(2)
    expect(posts[1].history).toEqual([]) // the failed question is not duplicated into history
    expect(screen.getAllByText('hello')).toHaveLength(1)
  })

  it('shows the unavailable state when Gemini is not configured and offers no fake replies', async () => {
    status = STATUS_OFF
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: 'Open Earth Scope AI assistant' }))
    expect(await screen.findByText('AI Assistant is not configured yet.')).toBeInTheDocument()
    expect(screen.getByLabelText('Ask about this analysis')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Summarize this analysis' })).not.toBeInTheDocument()
    expect(posts).toHaveLength(0)
  })

  it('announces an analysis change and does not mix the previous analysis into the next request', async () => {
    render(<Harness />)
    await open()
    typeAndSend('about Colombo')
    await screen.findByText('An answer.')
    fireEvent.click(screen.getByRole('button', { name: 'switch analysis' }))
    expect(await screen.findByText(/different analysis/)).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent('Air Temperature at London, 2001–2025')
    typeAndSend('and here?')
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].history).toEqual([])
    expect((posts[1].reference as { place: string }).place).toBe('London')
    fireEvent.click(screen.getByRole('button', { name: 'Start a new conversation for this page' }))
    expect(screen.queryByText('about Colombo')).not.toBeInTheDocument()
  })

  it('renders model Markdown safely (no HTML elements from the reply)', async () => {
    replies.push({ body: { reply: '<img src=x onerror="alert(1)"> **Bold** text\n\n- one\n- two\n\n<script>alert(2)</script>', context_id: null, context_label: null, has_results: true, model: null, usage: null, generated: true } })
    const { container } = render(<Harness />)
    await open()
    typeAndSend('hi')
    await screen.findByText('Bold')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(screen.getByText('Bold').tagName).toBe('STRONG')
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument()
    expect(within(screen.getByRole('log')).getAllByRole('listitem')).toHaveLength(2)
  })

  it('Escape minimizes the panel and returns focus to the launcher', async () => {
    render(<Harness />)
    await open()
    fireEvent.keyDown(screen.getByLabelText('Ask about this analysis'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Earth Scope AI assistant' })).toHaveFocus()
  })

  it('uses the shared theme tokens (works in light and dark) and a mobile bottom-sheet layout', async () => {
    for (const theme of ['light', 'dark']) {
      document.documentElement.dataset.theme = theme
      const { unmount } = render(<Harness />)
      await open()
      const dialog = screen.getByRole('dialog')
      expect(dialog.className).toMatch(/bg-surface/)
      expect(dialog.className).toMatch(/text-fg/)
      expect(dialog.className).not.toMatch(/#[0-9a-f]{3,6}/i)
      // Mobile: full-width sheet from the bottom edge; ≥ sm: compact floating window.
      expect(dialog.className).toMatch(/inset-x-0/)
      expect(dialog.className).toMatch(/sm:w-\[min\(400px/)
      expect(dialog.className).toMatch(/env\(safe-area-inset-bottom\)/)
      unmount()
    }
    delete document.documentElement.dataset.theme
  })

  it('includes Spatial Trend Explorer settings and shows heatmap suggestions on regional pages', async () => {
    render(<Harness initial={REGION} spatial={{ method: 'mann_kendall', correction: 'fdr_bh', alpha: 0.05, layer: 'significance', selected_cell_id: '7.0_80.0' }} />)
    await open()
    fireEvent.click(screen.getByRole('button', { name: 'Explain this heatmap' }))
    await screen.findByText('An answer.')
    expect(posts[0].page_type).toBe('regional_results')
    expect(posts[0].reference).toMatchObject({ area: { kind: 'rectangle' }, spatial: { layer: 'significance', selected_cell_id: '7.0_80.0' } })
  })
})

describe('context helpers', () => {
  it('chooses relevant quick actions per page', () => {
    expect(quickActionsFor(POINT, false).map((a) => a.label)).toContain('What does this chart mean?')
    expect(quickActionsFor(REGION, true).map((a) => a.label)).toContain('What is FDR correction?')
    expect(quickActionsFor(learnContext('p-values'), false).map((a) => a.label)).toEqual(['Explain this concept simply'])
    const job = { ...POINT, pageType: 'job_details' as const, hasResults: false }
    expect(quickActionsFor(job, false).map((a) => a.label)).toEqual(['Explain this job status', 'What happens during processing?'])
  })

  it('point analysis key ignores the display-only place name', () => {
    const p = { variable: 'T2M', latitude: 6.93, longitude: 79.85, startYear: 2001, endYear: 2025 }
    expect(pointContext(p, undefined, 'Air Temperature').analysisKey).toBe(pointContext(p, 'Colombo', 'Air Temperature').analysisKey)
  })

  it('safe Markdown keeps tags as text', () => {
    const { container } = render(<div>{renderSafeMarkdown('# Title\n1. a\n2. b\n`<b>x</b>`')}</div>)
    expect(container.querySelector('b')).toBeNull()
    expect(container.querySelectorAll('ol li')).toHaveLength(2)
  })
})
