import { useMemo } from 'react'

import type { Member, TreeNode } from '../api/types'
import type { Visibility } from '../lib/filter'
import { STATUS_COLORS, STATUS_LABELS } from '../lib/format'
import { ancestorIds, childrenOf, rootNodes, tagsOf, type TreeIndex } from '../lib/tree'

interface Props {
  index: TreeIndex
  visibility: Visibility
  members: Member[]
  /** The node whose children are on screen. null means the top of the tree. */
  focusId: number | null
  selectedId: number | null
  isolate: boolean
  onFocus: (id: number | null) => void
  onSelect: (id: number) => void
}

/**
 * One level of the tree at a time, as cards you click through.
 *
 * The same data as TreeView, navigated differently: the tree shows the whole
 * structure at once and asks you to find your way down it, this shows exactly
 * one level and asks you to walk. Better for "what is in Electrical?" and for a
 * phone, where a deep tree is mostly indentation.
 *
 * No new backend and no new state shape -- buildIndex() already keeps a
 * parent/child map, and the materialized path already encodes the ancestor
 * chain, so the breadcrumb is a lookup rather than a traversal. The only state
 * this adds is `focusId`, which node's children to draw.
 */
export function FlowView({
  index,
  visibility,
  members,
  focusId,
  selectedId,
  isolate,
  onFocus,
  onSelect,
}: Props) {
  const roots = rootNodes(index)

  // focusId === null means "the top". With the usual single-vehicle tree that
  // resolves to the root node itself, so the first screen is the vehicle with
  // its subsystems as cards -- not a lone card you have to click first.
  const focus = focusId != null ? (index.byId.get(focusId) ?? null) : roots.length === 1 ? roots[0] : null

  const cards = focus ? childrenOf(index, focus.id) : roots

  // Deliberately not memoized: it is a lookup per ancestor, and a part is five
  // levels down at worst. The two memos below are, because they walk every node
  // in the tree.
  const trail: TreeNode[] = focus
    ? [
        ...ancestorIds(focus)
          .map((id) => index.byId.get(id))
          .filter((n): n is TreeNode => Boolean(n)),
        focus,
      ]
    : []

  // Subtree sizes for the "N inside" hint. One pass over the flat node list
  // rather than a walk per card: every node's path already contains its
  // ancestors, so incrementing each ancestor is O(nodes x depth).
  const subtreeCount = useMemo(() => {
    const counts = new Map<number, number>()
    for (const node of index.nodes) {
      for (const id of ancestorIds(node)) {
        counts.set(id, (counts.get(id) ?? 0) + 1)
      }
    }
    return counts
  }, [index])

  const memberName = useMemo(() => {
    const byId = new Map(members.map((m) => [m.id, m.name]))
    return (id: number | null) => (id == null ? null : (byId.get(id) ?? null))
  }, [members])

  const shown = visibility.active && isolate
    ? cards.filter((n) => visibility.visible.has(n.id))
    : cards

  // Up goes to the parent, or to the multi-root "All" screen. On the usual
  // single-vehicle tree the root has nowhere above it, so Up is disabled there
  // rather than looping back onto the same screen.
  const parentId = focus?.parent_id ?? null
  const canGoUp = focus != null && (focus.parent_id != null || roots.length > 1)

  return (
    <div className="flow">
      <nav className="flow-crumbs" aria-label="Breadcrumb">
        <button
          type="button"
          className="crumb"
          disabled={!canGoUp}
          onClick={() => onFocus(parentId)}
          title="Up one level"
        >
          ↑ Up
        </button>

        {/* Only rendered when there is more than one root, because with a single
            vehicle the first crumb below is already the top of the tree. */}
        {roots.length > 1 && (
          <>
            <button type="button" className="crumb" onClick={() => onFocus(null)}>
              All
            </button>
            {trail.length > 0 && <span className="crumb-sep">›</span>}
          </>
        )}

        {trail.map((node, i) => (
          <span key={node.id} className="crumb-item">
            {i > 0 && <span className="crumb-sep">›</span>}
            <button
              type="button"
              className={`crumb${i === trail.length - 1 ? ' current' : ''}`}
              onClick={() => {
                onFocus(node.id)
                onSelect(node.id)
              }}
              // The last crumb is where you already are; clicking it should
              // still select it so the detail panel opens.
              title={i === trail.length - 1 ? 'You are here' : `Go to ${node.name}`}
            >
              {node.name}
            </button>
          </span>
        ))}
      </nav>

      {shown.length === 0 && (
        <p className="loading">
          {cards.length === 0
            ? 'Nothing inside this one — it is a part, not an assembly.'
            : 'Nothing here matches the filter.'}
        </p>
      )}

      <div className="flow-cards">
        {shown.map((node) => {
          const kids = childrenOf(index, node.id).length
          const inside = subtreeCount.get(node.id) ?? 0
          const assignee = memberName(node.assignee_id)
          const tags = tagsOf(index, node.id)
          // Three states, the same ones the tree draws. A card is not just
          // match/miss: at the top level a search for "sensor" matches nothing
          // on screen, and dimming all nine would say "nothing here" about the
          // one subsystem you actually need to open. `visible` is matched plus
          // the ancestors leading to a match, so that card stays lit as the
          // route in.
          const isMatch = visibility.matched.has(node.id)
          const onPath = visibility.visible.has(node.id)
          const dimmed = visibility.active && !onPath
          const context = visibility.active && onPath && !isMatch
          const files = index.attachmentCounts.get(node.id) ?? 0

          return (
            <button
              key={node.id}
              type="button"
              className={[
                'flow-card',
                node.id === selectedId ? 'selected' : '',
                dimmed ? 'dim' : '',
                context ? 'context' : '',
                kids ? 'has-children' : 'is-leaf',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => {
                // Always select, so the detail panel follows what you clicked.
                // Drill in as well when there is something inside -- that is the
                // whole point of the view, and a leaf has nowhere to go.
                onSelect(node.id)
                if (kids) onFocus(node.id)
              }}
            >
              <span className="flow-card-head">
                <span
                  className="status-pip"
                  style={{ background: STATUS_COLORS[node.status] }}
                  title={STATUS_LABELS[node.status]}
                />
                {node.node_type !== 'part' && (
                  <span className="node-type-badge" data-type={node.node_type}>
                    {node.node_type.slice(0, 4)}
                  </span>
                )}
                {node.quantity > 1 && <span className="node-qty">{`x${node.quantity}`}</span>}
              </span>

              <span className="flow-card-name">{node.name}</span>

              {node.part_number && <span className="flow-card-pn">{node.part_number}</span>}

              <span className="flow-card-meta">
                <span className="flow-card-status">{STATUS_LABELS[node.status]}</span>
                {assignee && <span className="flow-card-who">{assignee}</span>}
                {files > 0 && <span className="flow-card-files">{`${files} file${files === 1 ? '' : 's'}`}</span>}
              </span>

              {tags.length > 0 && (
                <span className="flow-card-tags" aria-hidden="true">
                  {tags.slice(0, 5).map((t) => (
                    <span key={t.tag_id} className="dot" style={{ background: t.color }} />
                  ))}
                  {tags.length > 5 && <span className="flow-card-more">{`+${tags.length - 5}`}</span>}
                </span>
              )}

              {/* The affordance that says this one opens. A leaf says nothing,
                  so the two are distinguishable before you click. */}
              {kids > 0 && (
                <span className="flow-card-open">
                  {context ? 'match inside' : `${kids} inside`}
                  {inside > kids && <span className="flow-card-deep">{` · ${inside} total`}</span>}
                  <span className="flow-card-arrow">›</span>
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
