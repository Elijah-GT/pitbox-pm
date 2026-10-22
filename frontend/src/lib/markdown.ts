/**
 * A small Markdown parser for the Learn pages.
 *
 * It returns a tree of plain objects, and components/Markdown.tsx turns that
 * tree into React elements. Nothing here ever produces an HTML string, so the
 * app has no dangerouslySetInnerHTML anywhere and nothing a teammate types can
 * become markup: "<script>" in a writeup renders as those eight characters.
 * That holds by construction, rather than by a sanitizer having to be right.
 *
 * Deliberately a subset -- what a writeup actually uses:
 *
 *   ## Heading / ### Sub-heading        paragraphs, joined across lines
 *   - bullets / 1. numbers (nestable)   > notes (rendered as a callout)
 *   **bold**  *italic*  `code`          ```fenced code```
 *   [text](https://...)                 ![caption](picture URL), alone on a line
 *   | tables | with | alignment |       ---  (a rule)
 *
 * Two rules worth knowing:
 *
 *   * An underscore inside a word is just an underscore. RIGHT_SIM_FORE is a
 *     part name, not "RIGHT" + italic "SIM" + "FORE".
 *   * Links must be http(s), mailto, or a link to another Learn page; pictures
 *     must be https or one uploaded here. Anything else -- javascript:, data:
 *     -- keeps its words and loses the link.
 *
 * Self-contained, with no imports, so `node --test` can load it directly.
 * See frontend/tests/markdown.test.ts.
 */

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; children: Inline[] }
  | { kind: 'em'; children: Inline[] }
  | { kind: 'code'; text: string }
  | { kind: 'link'; href: string; external: boolean; children: Inline[] }
  | { kind: 'image'; src: string; alt: string }

export type Align = 'left' | 'center' | 'right' | null

export interface ListItem {
  children: Inline[]
  /** A nested list under this item, if any. */
  sub: Block[]
}

export type Block =
  | { kind: 'heading'; level: 2 | 3 | 4; children: Inline[] }
  | { kind: 'paragraph'; children: Inline[] }
  | { kind: 'list'; ordered: boolean; start: number; items: ListItem[] }
  | { kind: 'quote'; blocks: Block[] }
  | { kind: 'code'; lang: string; text: string }
  | { kind: 'rule' }
  | { kind: 'figure'; src: string; alt: string }
  | { kind: 'table'; head: Inline[][]; align: Align[]; rows: Inline[][][] }

/* ------------------------------------------------------------------ URLs */

const LEARN_IMAGE = /^\/api\/learn\/images\/\d+$/

/** Where a link may point. null means "show the words, not a link". */
export function safeHref(raw: string): { href: string; external: boolean } | null {
  const url = raw.trim()
  if (/^https?:\/\//i.test(url) || /^mailto:/i.test(url)) return { href: url, external: true }
  // Another Learn page, or a picture stored with one.
  if (/^#\/learn(\/[\w/-]*)?$/.test(url) || LEARN_IMAGE.test(url)) {
    return { href: url, external: false }
  }
  return null
}

/** Where a picture may load from. https only for outside images: this page
 *  is served over https, and a plain-http picture would be blocked anyway. */
export function safeImageSrc(raw: string): string | null {
  const url = raw.trim()
  return LEARN_IMAGE.test(url) || /^https:\/\//i.test(url) ? url : null
}

/* ---------------------------------------------------------------- blocks */

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/
const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/
const QUOTE = /^ {0,3}>\s?(.*)$/
const ITEM = /^( *)([-*+]|\d{1,9}[.)])\s+(.*)$/
// One dash is enough -- ":-:" is a valid centred column. What stops a "---"
// rule being mistaken for this is the cell-count check in startsTable().
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/

const isBlank = (line: string) => line.trim() === ''
const indentOf = (line: string) => line.length - line.trimStart().length
const isOrdered = (marker: string) => /\d/.test(marker)

function startsTable(lines: string[], i: number): boolean {
  const next = lines[i + 1]
  // The separator must have as many cells as the header. Without that, a
  // sentence containing "|" followed by a --- rule reads as a table.
  return (
    lines[i].includes('|') &&
    next !== undefined &&
    TABLE_SEP.test(next) &&
    splitRow(next).length === splitRow(lines[i]).length
  )
}

function isBlockStart(lines: string[], i: number): boolean {
  const line = lines[i]
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    ITEM.test(line) ||
    startsTable(lines, i)
  )
}

export function parseMarkdown(src: string): Block[] {
  // Normalise line endings and tabs once, so nothing below has to care.
  const lines = src.replace(/\r\n?/g, '\n').replace(/\t/g, '    ').split('\n')
  return parseBlocks(lines)
}

function parseBlocks(lines: string[]): Block[] {
  const out: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (isBlank(line)) {
      i += 1
      continue
    }

    const fence = FENCE.exec(line)
    if (fence) {
      const close = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}\\s*$`)
      const body: string[] = []
      i += 1
      while (i < lines.length && !close.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      // Past the closing fence -- or off the end: an unclosed fence takes
      // the rest of the page, which is what the writer can see they did.
      i += 1
      out.push({ kind: 'code', lang: fence[2], text: body.join('\n') })
      continue
    }

    const heading = HEADING.exec(line)
    if (heading) {
      // The page title is the only h1, so "#" and "##" are both section
      // headings and the deepest level is h4.
      const level = Math.min(4, Math.max(2, heading[1].length)) as 2 | 3 | 4
      out.push({ kind: 'heading', level, children: parseInline(heading[2]) })
      i += 1
      continue
    }

    if (RULE.test(line)) {
      out.push({ kind: 'rule' })
      i += 1
      continue
    }

    if (QUOTE.test(line)) {
      const inner: string[] = []
      while (i < lines.length && QUOTE.test(lines[i])) {
        inner.push((QUOTE.exec(lines[i]) as RegExpExecArray)[1])
        i += 1
      }
      out.push({ kind: 'quote', blocks: parseBlocks(inner) })
      continue
    }

    if (startsTable(lines, i)) {
      i = parseTable(lines, i, out)
      continue
    }

    if (ITEM.test(line)) {
      i = parseList(lines, i, out)
      continue
    }

    const para = [line.trim()]
    i += 1
    while (i < lines.length && !isBlank(lines[i]) && !isBlockStart(lines, i)) {
      para.push(lines[i].trim())
      i += 1
    }
    out.push(paragraphOrFigure(para.join(' ')))
  }
  return out
}

/** A paragraph that is nothing but one picture becomes a captioned figure. */
function paragraphOrFigure(text: string): Block {
  const children = parseInline(text)
  const solid = children.filter((n) => !(n.kind === 'text' && n.text.trim() === ''))
  if (solid.length === 1 && solid[0].kind === 'image') {
    return { kind: 'figure', src: solid[0].src, alt: solid[0].alt }
  }
  return { kind: 'paragraph', children }
}

function parseList(lines: string[], start: number, out: Block[]): number {
  const first = ITEM.exec(lines[start]) as RegExpExecArray
  const base = first[1].length
  const ordered = isOrdered(first[2])
  const items: ListItem[] = []

  let text: string[] = [first[3]]
  let nested: string[] = []
  const finish = () => {
    items.push({
      children: parseInline(text.join(' ')),
      sub: nested.length ? parseBlocks(dedent(nested)) : [],
    })
    text = []
    nested = []
  }

  let i = start + 1
  while (i < lines.length) {
    const line = lines[i]

    if (isBlank(line)) {
      // A blank line ends the list -- unless what follows is another item of
      // this list, or more of the current item indented underneath it.
      const next = nextNonBlank(lines, i)
      if (next === -1) break
      const m = ITEM.exec(lines[next])
      const sameList = m !== null && indentOf(lines[next]) <= base + 1 && isOrdered(m[2]) === ordered
      if (sameList || indentOf(lines[next]) >= base + 2) {
        i = next
        continue
      }
      break
    }

    const m = ITEM.exec(line)
    const indent = indentOf(line)

    if (m && indent <= base + 1) {
      if (isOrdered(m[2]) !== ordered) break // a different kind of list starts here
      finish()
      text = [m[3]]
      i += 1
      continue
    }

    if (indent >= base + 2) {
      // Indented under the current item: either a nested list, or the
      // item's own text wrapped onto the next line.
      if (m || nested.length) nested.push(line)
      else text.push(line.trim())
      i += 1
      continue
    }

    if (isBlockStart(lines, i)) break
    // Unindented text straight after an item still belongs to it.
    text.push(line.trim())
    i += 1
  }

  finish()
  out.push({ kind: 'list', ordered, start: ordered ? parseInt(first[2], 10) : 1, items })
  return i
}

function nextNonBlank(lines: string[], from: number): number {
  for (let k = from; k < lines.length; k += 1) {
    if (!isBlank(lines[k])) return k
  }
  return -1
}

function dedent(lines: string[]): string[] {
  const margin = Math.min(...lines.filter((l) => !isBlank(l)).map(indentOf))
  return lines.map((l) => l.slice(margin))
}

function parseTable(lines: string[], start: number, out: Block[]): number {
  const head = splitRow(lines[start])
  const width = head.length
  const align = splitRow(lines[start + 1]).map(alignOf)
  const rows: Inline[][][] = []

  let i = start + 2
  while (i < lines.length && !isBlank(lines[i]) && lines[i].includes('|')) {
    const cells = splitRow(lines[i])
    // Every row as wide as the header: short rows padded, long ones trimmed,
    // so a missing pipe cannot shift a whole column sideways.
    rows.push(Array.from({ length: width }, (_, c) => parseInline(cells[c] ?? '')))
    i += 1
  }

  out.push({
    kind: 'table',
    head: head.map(parseInline),
    align: Array.from({ length: width }, (_, c) => align[c] ?? null),
    rows,
  })
  return i
}

function splitRow(line: string): string[] {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1)

  const cells: string[] = []
  let cell = ''
  for (let k = 0; k < s.length; k += 1) {
    if (s[k] === '\\' && s[k + 1] === '|') {
      cell += '|'
      k += 1
    } else if (s[k] === '|') {
      cells.push(cell.trim())
      cell = ''
    } else {
      cell += s[k]
    }
  }
  cells.push(cell.trim())
  return cells
}

function alignOf(cell: string): Align {
  const left = cell.startsWith(':')
  const right = cell.endsWith(':')
  if (left && right) return 'center'
  if (right) return 'right'
  return left ? 'left' : null
}

/* ---------------------------------------------------------------- inline */

const ESCAPABLE = new Set('\\`*_{}[]()#+-.!|>~'.split(''))

const isSpace = (ch: string | undefined) => ch === undefined || /\s/.test(ch)
const isWordChar = (ch: string | undefined) => ch !== undefined && /[\p{L}\p{N}]/u.test(ch)

function runLength(src: string, at: number, ch: string): number {
  let n = 0
  while (src[at + n] === ch) n += 1
  return n
}

/** Where a run of exactly `n` of `ch` starts, from `from` on, or -1. */
function findRun(src: string, from: number, ch: string, n: number): number {
  let k = from
  while (k < src.length) {
    const at = src.indexOf(ch, k)
    if (at === -1) return -1
    const run = runLength(src, at, ch)
    if (run === n) return at
    k = at + run
  }
  return -1
}

/** Append, merging neighbouring text so the tree stays small and predictable. */
function push(out: Inline[], node: Inline): void {
  const last = out[out.length - 1]
  if (node.kind === 'text' && last?.kind === 'text') {
    out[out.length - 1] = { kind: 'text', text: last.text + node.text }
  } else if (node.kind !== 'text' || node.text) {
    out.push(node)
  }
}

export function parseInline(src: string): Inline[] {
  const out: Inline[] = []
  let p = 0

  while (p < src.length) {
    const ch = src[p]

    if (ch === '\\' && ESCAPABLE.has(src[p + 1] ?? '')) {
      push(out, { kind: 'text', text: src[p + 1] })
      p += 2
      continue
    }

    if (ch === '`') {
      const run = runLength(src, p, '`')
      const close = findRun(src, p + run, '`', run)
      if (close !== -1) {
        let code = src.slice(p + run, close)
        if (code.length > 2 && code.startsWith(' ') && code.endsWith(' ')) code = code.slice(1, -1)
        push(out, { kind: 'code', text: code })
        p = close + run
      } else {
        push(out, { kind: 'text', text: src.slice(p, p + run) })
        p += run
      }
      continue
    }

    if (ch === '!' && src[p + 1] === '[') {
      const found = linkish(src, p + 1)
      if (found) {
        const safe = safeImageSrc(found.url)
        // A picture from somewhere we will not load from keeps its caption
        // as text, so the writer can see something is wrong.
        push(out, safe ? { kind: 'image', src: safe, alt: found.text } : { kind: 'text', text: found.text })
        p = found.end
        continue
      }
    }

    if (ch === '[') {
      const found = linkish(src, p)
      if (found) {
        const children = parseInline(found.text)
        const safe = safeHref(found.url)
        if (safe) push(out, { kind: 'link', href: safe.href, external: safe.external, children })
        else for (const child of children) push(out, child)
        p = found.end
        continue
      }
    }

    if (ch === '*' || ch === '_') {
      const em = emphasis(src, p)
      if (em) {
        push(out, em.node)
        p = em.end
      } else {
        const run = runLength(src, p, ch)
        push(out, { kind: 'text', text: src.slice(p, p + run) })
        p += run
      }
      continue
    }

    // A bare link pasted into a sentence -- the usual way an Onshape URL
    // arrives -- becomes clickable without brackets.
    if ((ch === 'h' || ch === 'H') && /^https?:\/\//i.test(src.slice(p, p + 8)) && isSpaceOrOpen(src[p - 1])) {
      let end = p
      while (end < src.length && !/[\s<>]/.test(src[end])) end += 1
      let url = src.slice(p, end)
      // Sentence punctuation after a link is not part of it.
      while (/[.,;:!?'"]$/.test(url) || (url.endsWith(')') && !url.includes('('))) {
        url = url.slice(0, -1)
      }
      push(out, { kind: 'link', href: url, external: true, children: [{ kind: 'text', text: url }] })
      p += url.length
      continue
    }

    push(out, { kind: 'text', text: ch })
    p += 1
  }
  return out
}

const isSpaceOrOpen = (ch: string | undefined) => ch === undefined || /[\s(]/.test(ch)

/** `[text](url)` starting at the "[" -- or null if it is just a bracket. */
function linkish(src: string, open: number): { text: string; url: string; end: number } | null {
  let depth = 0
  let k = open
  for (; k < src.length; k += 1) {
    if (src[k] === '\\') {
      k += 1
    } else if (src[k] === '[') {
      depth += 1
    } else if (src[k] === ']') {
      depth -= 1
      if (depth === 0) break
    }
  }
  if (k >= src.length || src[k + 1] !== '(') return null

  let q = k + 2
  let parens = 0
  for (; q < src.length; q += 1) {
    if (src[q] === '(') parens += 1
    else if (src[q] === ')') {
      if (parens === 0) break
      parens -= 1
    }
  }
  if (q >= src.length) return null

  let url = src.slice(k + 2, q).trim()
  // An optional "title" after the URL is accepted and ignored.
  const titled = /^(\S+)\s+["'].*["']$/.exec(url)
  if (titled) url = titled[1]
  if (url.startsWith('<') && url.endsWith('>')) url = url.slice(1, -1)
  return { text: src.slice(open + 1, k), url, end: q + 1 }
}

/** **strong** or *em* (or the underscore forms) starting at `p`, or null. */
function emphasis(src: string, p: number): { node: Inline; end: number } | null {
  const ch = src[p]
  const size = runLength(src, p, ch) >= 2 ? 2 : 1

  // "* item" and "2 * 3" are not emphasis.
  if (isSpace(src[p + size])) return null
  // RIGHT_SIM_FORE: an underscore inside a word is part of the word.
  if (ch === '_' && isWordChar(src[p - 1])) return null

  let q = p + size
  while (q < src.length) {
    const found = src.indexOf(ch, q)
    if (found === -1) return null
    const run = runLength(src, found, ch)

    // Looking for a single "*": a "**" pair inside is bold, not our closer.
    if (size === 1 && run === 2) {
      q = found + run
      continue
    }
    if (run < size || isSpace(src[found - 1])) {
      q = found + run
      continue
    }
    // Use the END of a longer run, so ***both*** nests as bold-then-italic.
    const close = found + run - size
    if (ch === '_' && isWordChar(src[close + size])) {
      q = found + run
      continue
    }

    const inner = src.slice(p + size, close)
    if (!inner) return null
    const children = parseInline(inner)
    return {
      node: size === 2 ? { kind: 'strong', children } : { kind: 'em', children },
      end: close + size,
    }
  }
  return null
}
