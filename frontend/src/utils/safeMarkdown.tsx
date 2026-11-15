import type { ReactNode } from 'react'

/**
 * Minimal, SAFE Markdown: paragraphs, headings, bullet / numbered lists, **bold**, *italic* and
 * `code`. Everything is emitted as React text nodes — model output is never parsed as HTML, so
 * tags, scripts and event handlers in a reply are shown as plain text and never executed.
 * Links are rendered as text (no clickable URLs from the model).
 */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)/g
  let last = 0
  let i = 0
  for (const m of text.matchAll(re)) {
    const idx = m.index ?? 0
    if (idx > last) out.push(text.slice(last, idx))
    const tok = m[0]
    const k = `${keyBase}-${i++}`
    if (tok.startsWith('**')) out.push(<strong key={k} className="font-semibold text-fg">{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) out.push(<code key={k} className="rounded bg-sunken px-1 py-0.5 font-mono text-[0.85em]">{tok.slice(1, -1)}</code>)
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>)
    last = idx + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

type TextBlock = { kind: 'p' | 'h' | 'hr'; text: string }
type ListBlock = { kind: 'ul' | 'ol'; items: string[] }
type Block = TextBlock | ListBlock
const isList = (b: Block): b is ListBlock => b.kind === 'ul' || b.kind === 'ol'

export function renderSafeMarkdown(src: string): ReactNode {
  const blocks: Block[] = []
  let para: string[] = []
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') })
    para = []
  }
  for (const raw of src.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line)
    if (!line.trim()) {
      flush()
    } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      flush()
      blocks.push({ kind: 'hr', text: '' })
    } else if (heading) {
      flush()
      blocks.push({ kind: 'h', text: heading[1] })
    } else if (bullet || numbered) {
      flush()
      const kind = bullet ? 'ul' : 'ol'
      const item = (bullet ?? numbered)![1]
      const prev = blocks[blocks.length - 1]
      if (prev && isList(prev) && prev.kind === kind) prev.items.push(item)
      else blocks.push({ kind, items: [item] })
    } else {
      para.push(line.trim())
    }
  }
  flush()
  return blocks.map((b, bi) => {
    if (!isList(b)) {
      if (b.kind === 'hr') return <hr key={bi} className="border-line" />
      return b.kind === 'h' ? (
        <p key={bi} className="font-semibold text-fg">{inline(b.text, `h${bi}`)}</p>
      ) : (
        <p key={bi}>{inline(b.text, `p${bi}`)}</p>
      )
    }
    const items = b.items.map((it, ii) => <li key={ii}>{inline(it, `l${bi}-${ii}`)}</li>)
    return b.kind === 'ul' ? (
      <ul key={bi} className="list-disc space-y-1 pl-5">{items}</ul>
    ) : (
      <ol key={bi} className="list-decimal space-y-1 pl-5">{items}</ol>
    )
  })
}
