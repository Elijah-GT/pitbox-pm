// Tests for the Learn page's Markdown parser. Run with:  npm test
//
// Node runs TypeScript directly (type stripping), so this needs no test
// framework and no build step -- the same reason the parser has no imports.

import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  type Block,
  type Inline,
  parseInline,
  parseMarkdown,
  safeHref,
  safeImageSrc,
} from '../src/lib/markdown.ts'

/** Flatten inline nodes back to their visible text. */
function plain(nodes: Inline[]): string {
  return nodes
    .map((n) => {
      if (n.kind === 'text' || n.kind === 'code') return n.text
      if (n.kind === 'image') return n.alt
      return plain(n.children)
    })
    .join('')
}

function only<K extends Block['kind']>(blocks: Block[], kind: K): Extract<Block, { kind: K }> {
  assert.equal(blocks.length, 1, `expected one block, got ${JSON.stringify(blocks)}`)
  assert.equal(blocks[0].kind, kind)
  return blocks[0] as Extract<Block, { kind: K }>
}

/* ---------------------------------------------------------- safety first */

test('nothing typed becomes markup: tags are just text', () => {
  const para = only(parseMarkdown('<script>alert(1)</script> <img src=x onerror=alert(1)>'), 'paragraph')
  assert.deepEqual(para.children, [
    { kind: 'text', text: '<script>alert(1)</script> <img src=x onerror=alert(1)>' },
  ])
})

test('a javascript: link keeps its words and loses the link', () => {
  for (const url of ['javascript:alert(1)', 'JavaScript:alert(1)', ' javascript:x', 'data:text/html,hi', 'vbscript:x']) {
    const nodes = parseInline(`[click me](${url})`)
    assert.deepEqual(nodes, [{ kind: 'text', text: 'click me' }], url)
  }
})

test('only safe places are linkable', () => {
  assert.deepEqual(safeHref('https://cad.onshape.com/documents/abc'), {
    href: 'https://cad.onshape.com/documents/abc',
    external: true,
  })
  assert.deepEqual(safeHref('#/learn/page/12'), { href: '#/learn/page/12', external: false })
  assert.equal(safeHref('/etc/passwd'), null)
  assert.equal(safeHref('//evil.example/x'), null)
  assert.equal(safeHref('#/learn/x" onclick="y'), null)
})

test('pictures load only from here or over https', () => {
  assert.equal(safeImageSrc('/api/learn/images/7'), '/api/learn/images/7')
  assert.equal(safeImageSrc('https://example.com/a.png'), 'https://example.com/a.png')
  assert.equal(safeImageSrc('http://example.com/a.png'), null)
  assert.equal(safeImageSrc('data:image/png;base64,AAAA'), null)
  assert.equal(safeImageSrc('/api/learn/images/7/../../members'), null)
  // An unloadable picture shows its caption, so the writer notices.
  assert.deepEqual(parseInline('![the rack](javascript:x)'), [{ kind: 'text', text: 'the rack' }])
})

/* -------------------------------------------------------------- inline */

test('an underscore inside a word is part of the word', () => {
  assert.deepEqual(parseInline('Cut RIGHT_SIM_FORE first'), [
    { kind: 'text', text: 'Cut RIGHT_SIM_FORE first' },
  ])
  assert.deepEqual(parseInline('FBM_L_Front_Drawing'), [{ kind: 'text', text: 'FBM_L_Front_Drawing' }])
})

test('underscores around a word still mean italics', () => {
  assert.deepEqual(parseInline('use _care_ here'), [
    { kind: 'text', text: 'use ' },
    { kind: 'em', children: [{ kind: 'text', text: 'care' }] },
    { kind: 'text', text: ' here' },
  ])
})

test('bold, italic, and both', () => {
  assert.deepEqual(parseInline('**bold** and *it*'), [
    { kind: 'strong', children: [{ kind: 'text', text: 'bold' }] },
    { kind: 'text', text: ' and ' },
    { kind: 'em', children: [{ kind: 'text', text: 'it' }] },
  ])
  assert.deepEqual(parseInline('***both***'), [
    { kind: 'strong', children: [{ kind: 'em', children: [{ kind: 'text', text: 'both' }] }] },
  ])
  assert.deepEqual(parseInline('*a **b** c*'), [
    {
      kind: 'em',
      children: [
        { kind: 'text', text: 'a ' },
        { kind: 'strong', children: [{ kind: 'text', text: 'b' }] },
        { kind: 'text', text: ' c' },
      ],
    },
  ])
})

test('stray stars and unclosed markers stay literal', () => {
  assert.equal(plain(parseInline('2 * 3 = 6')), '2 * 3 = 6')
  assert.deepEqual(parseInline('**never closed'), [{ kind: 'text', text: '**never closed' }])
  assert.deepEqual(parseInline('\\*not italic\\*'), [{ kind: 'text', text: '*not italic*' }])
})

test('code spans are literal inside', () => {
  assert.deepEqual(parseInline('set `**x**` to `a_b`'), [
    { kind: 'text', text: 'set ' },
    { kind: 'code', text: '**x**' },
    { kind: 'text', text: ' to ' },
    { kind: 'code', text: 'a_b' },
  ])
  assert.deepEqual(parseInline('`` a ` b ``'), [{ kind: 'code', text: 'a ` b' }])
})

test('links, with formatting inside', () => {
  assert.deepEqual(parseInline('see [the **rack** model](https://cad.onshape.com/d/1)'), [
    { kind: 'text', text: 'see ' },
    {
      kind: 'link',
      href: 'https://cad.onshape.com/d/1',
      external: true,
      children: [
        { kind: 'text', text: 'the ' },
        { kind: 'strong', children: [{ kind: 'text', text: 'rack' }] },
        { kind: 'text', text: ' model' },
      ],
    },
  ])
})

test('a pasted URL becomes a link, without the full stop after it', () => {
  const nodes = parseInline('Model: https://cad.onshape.com/documents/abc/w/def. Done')
  assert.deepEqual(nodes[1], {
    kind: 'link',
    href: 'https://cad.onshape.com/documents/abc/w/def',
    external: true,
    children: [{ kind: 'text', text: 'https://cad.onshape.com/documents/abc/w/def' }],
  })
  assert.equal(plain(nodes), 'Model: https://cad.onshape.com/documents/abc/w/def. Done')
  // ...and the closing bracket of a parenthetical is not part of it either.
  const wrapped = parseInline('(see https://example.com/x)')
  assert.equal(wrapped[1].kind === 'link' && wrapped[1].href, 'https://example.com/x')
})

test('square brackets that are not links stay as written', () => {
  assert.equal(plain(parseInline('[draft] tube list')), '[draft] tube list')
})

/* -------------------------------------------------------------- blocks */

test('headings: the page title is h1, so # and ## are both h2', () => {
  const blocks = parseMarkdown('# A\n## B\n### C\n#### D\n###### E')
  assert.deepEqual(
    blocks.map((b) => (b.kind === 'heading' ? b.level : b.kind)),
    [2, 2, 3, 4, 4],
  )
  assert.equal(parseMarkdown('#hashtag')[0].kind, 'paragraph')
})

test('wrapped lines join into one paragraph; a blank line splits them', () => {
  const blocks = parseMarkdown('first line\nstill first\n\nsecond')
  assert.equal(blocks.length, 2)
  assert.equal(plain((blocks[0] as Extract<Block, { kind: 'paragraph' }>).children), 'first line still first')
})

test('bullets, with each item wrapped onto an indented line', () => {
  const list = only(
    parseMarkdown('- **Unique.** Two parts with the\n  same name get cut twice.\n- **Stable.** Rename in both places.'),
    'list',
  )
  assert.equal(list.ordered, false)
  assert.equal(list.items.length, 2)
  assert.equal(plain(list.items[0].children), 'Unique. Two parts with the same name get cut twice.')
})

test('numbered lists keep their starting number', () => {
  const list = only(parseMarkdown('3. third\n4. fourth\n   still fourth'), 'list')
  assert.equal(list.ordered, true)
  assert.equal(list.start, 3)
  assert.equal(plain(list.items[1].children), 'fourth still fourth')
})

test('a nested list hangs off its item', () => {
  const list = only(parseMarkdown('- shocks\n  - front\n  - rear\n- springs'), 'list')
  assert.equal(list.items.length, 2)
  const sub = only(list.items[0].sub, 'list')
  assert.deepEqual(sub.items.map((i) => plain(i.children)), ['front', 'rear'])
  assert.deepEqual(list.items[1].sub, [])
})

test('a blank line between items keeps one list; text after it ends the list', () => {
  const loose = only(parseMarkdown('- a\n\n- b'), 'list')
  assert.equal(loose.items.length, 2)
  const ended = parseMarkdown('- a\n\nafter')
  assert.deepEqual(ended.map((b) => b.kind), ['list', 'paragraph'])
})

test('switching from bullets to numbers starts a new list', () => {
  const blocks = parseMarkdown('- a\n1. b')
  assert.deepEqual(blocks.map((b) => b.kind), ['list', 'list'])
})

test('a note spanning several > lines is one callout', () => {
  const quote = only(parseMarkdown('> **Note:** this is a\n> living document.'), 'quote')
  const para = only(quote.blocks, 'paragraph')
  assert.equal(plain(para.children), 'Note: this is a living document.')
})

test('fenced code keeps everything exactly, Markdown included', () => {
  const code = only(parseMarkdown('```py\nx = a_b * 2\n## not a heading\n```'), 'code')
  assert.equal(code.lang, 'py')
  assert.equal(code.text, 'x = a_b * 2\n## not a heading')
})

test('an unclosed fence takes the rest of the page', () => {
  const code = only(parseMarkdown('```\nline one\nline two'), 'code')
  assert.equal(code.text, 'line one\nline two')
})

test('a picture alone on its line is a figure with its caption', () => {
  const fig = only(parseMarkdown('![Rear upright, view from inboard](/api/learn/images/3)'), 'figure')
  assert.deepEqual(fig, {
    kind: 'figure',
    src: '/api/learn/images/3',
    alt: 'Rear upright, view from inboard',
  })
})

test('tables, with alignment and ragged rows evened out', () => {
  const table = only(
    parseMarkdown('| Tube | OD | Wall |\n|:--|:-:|--:|\n| Main hoop | 1.25 | 0.065 |\n| Brace | 1.0 |'),
    'table',
  )
  assert.deepEqual(table.head.map(plain), ['Tube', 'OD', 'Wall'])
  assert.deepEqual(table.align, ['left', 'center', 'right'])
  assert.equal(table.rows.length, 2)
  assert.deepEqual(table.rows[1].map(plain), ['Brace', '1.0', ''])
})

test('a pipe in a sentence followed by a rule is not a table', () => {
  const blocks = parseMarkdown('either A | B works\n---')
  assert.deepEqual(blocks.map((b) => b.kind), ['paragraph', 'rule'])
})

test('Windows line endings and tabs parse the same as Unix ones', () => {
  assert.deepEqual(parseMarkdown('## T\r\n\r\n- a\r\n\t- b'), parseMarkdown('## T\n\n- a\n    - b'))
})

test('a starter page from the seed parses the way it reads', () => {
  const blocks = parseMarkdown(
    'How the CVT is tuned.\n\n' +
      '> **Starter outline.** Replace it with how *our* team does it.\n\n' +
      '## What to cover\n\n' +
      '- Which CVT the car runs\n' +
      '- Belt inspection and replacement\n',
  )
  assert.deepEqual(blocks.map((b) => b.kind), ['paragraph', 'quote', 'heading', 'list'])
})
