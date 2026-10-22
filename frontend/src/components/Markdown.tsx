import { useMemo, type ReactNode } from 'react'

import { type Block, type Inline, parseMarkdown } from '../lib/markdown'

/**
 * Renders a Learn writeup.
 *
 * Everything here is ordinary React children and attributes -- no
 * dangerouslySetInnerHTML -- so React escapes all text, and the only URLs that
 * reach an href or src are the ones lib/markdown.ts already vetted.
 */
export function Markdown({ source }: { source: string }) {
  const blocks = useMemo(() => parseMarkdown(source), [source])
  return (
    <div className="md">
      {blocks.map((block, i) => (
        <BlockView key={i} block={block} />
      ))}
    </div>
  )
}

function BlockView({ block }: { block: Block }): ReactNode {
  switch (block.kind) {
    case 'heading': {
      const Tag = `h${block.level}` as 'h2' | 'h3' | 'h4'
      return (
        <Tag>
          <Inlines nodes={block.children} />
        </Tag>
      )
    }
    case 'paragraph':
      return (
        <p>
          <Inlines nodes={block.children} />
        </p>
      )
    case 'list': {
      const items = block.items.map((item, i) => (
        <li key={i}>
          <Inlines nodes={item.children} />
          {item.sub.map((sub, j) => (
            <BlockView key={j} block={sub} />
          ))}
        </li>
      ))
      return block.ordered ? <ol start={block.start}>{items}</ol> : <ul>{items}</ul>
    }
    case 'quote':
      // Writeups use these for "Note:" and "Check the rules" callouts, so they
      // are styled as callouts rather than as quotations.
      return (
        <blockquote className="md-note">
          {block.blocks.map((inner, i) => (
            <BlockView key={i} block={inner} />
          ))}
        </blockquote>
      )
    case 'code':
      return (
        <pre className="md-code">
          <code>{block.text}</code>
        </pre>
      )
    case 'rule':
      return <hr />
    case 'figure':
      return (
        <figure className="md-figure">
          <img src={block.src} alt={block.alt} loading="lazy" />
          {block.alt && <figcaption>{block.alt}</figcaption>}
        </figure>
      )
    case 'table':
      // Wrapped so a wide spec table scrolls sideways on a phone instead of
      // pushing the whole page wider than the screen.
      return (
        <div className="md-table-wrap">
          <table>
            <thead>
              <tr>
                {block.head.map((cell, c) => (
                  <th key={c} style={{ textAlign: block.align[c] ?? undefined }}>
                    <Inlines nodes={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c} style={{ textAlign: block.align[c] ?? undefined }}>
                      <Inlines nodes={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
  }
}

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((node, i) => (
        <InlineView key={i} node={node} />
      ))}
    </>
  )
}

function InlineView({ node }: { node: Inline }): ReactNode {
  switch (node.kind) {
    case 'text':
      return node.text
    case 'strong':
      return (
        <strong>
          <Inlines nodes={node.children} />
        </strong>
      )
    case 'em':
      return (
        <em>
          <Inlines nodes={node.children} />
        </em>
      )
    case 'code':
      return <code>{node.text}</code>
    case 'link':
      // Outside links open in a new tab, so following an Onshape link does
      // not lose your place in the writeup. noopener: the new tab gets no
      // handle back on this one.
      return node.external ? (
        <a href={node.href} target="_blank" rel="noopener noreferrer">
          <Inlines nodes={node.children} />
        </a>
      ) : (
        <a href={node.href}>
          <Inlines nodes={node.children} />
        </a>
      )
    case 'image':
      return <img className="md-inline-img" src={node.src} alt={node.alt} loading="lazy" />
  }
}
