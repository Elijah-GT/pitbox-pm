import { useState } from 'react'
import type { CSSProperties } from 'react'

import type { TreeNode } from '../api/types'
import {
  gutterWidth,
  GUTTER_PAD,
  LANE_WIDTH,
  type ConnectionGroup,
} from '../lib/connections'
import type { Visibility } from '../lib/filter'
import { STATUS_COLORS, STATUS_LABELS } from '../lib/format'
import {
  ancestorIds,
  childrenOf,
  flattenVisible,
  tagsOf,
  type TreeIndex,
  type TreeRow,
} from '../lib/tree'

/**
 * Fixed row height. The connection gutter positions everything by row index
 * rather than by measuring the DOM, so this constant and the CSS must agree —
 * which is why the component sets --row-h from here instead of the stylesheet
 * declaring its own number.
 */
export const ROW_H = 26

/**
 * Indent per level. The edge layer for a row is exactly `(depth + 1) * INDENT`
 * wide, which is what makes a child's riser land under its parent's twisty:
 * the parent's own edge layer is one INDENT narrower, so its controls start
 * precisely where the child's elbow column begins.
 */
const INDENT = 18

/** Corner radius on a last-child elbow. */
const ELBOW_R = 6

interface Props {
  index: TreeIndex
  visibility: Visibility
  expanded: ReadonlySet<number>
  selectedId: number | null
  isolate: boolean
  groups: ConnectionGroup[]
  onToggle: (id: number) => void
  onSelect: (id: number) => void
  onAddChild: (node: TreeNode) => void
  onMove: (draggedId: number, targetId: number) => void
  onContextMenu: (node: TreeNode, x: number, y: number) => void
}

export function TreeView({
  index,
  visibility,
  expanded,
  selectedId,
  isolate,
  groups,
  onToggle,
  onSelect,
  onAddChild,
  onMove,
  onContextMenu,
}: Props) {
  const [dragId, setDragId] = useState<number | null>(null)
  const [dropId, setDropId] = useState<number | null>(null)

  // Isolate prunes to the visible set; highlight keeps everything and dims.
  const rows = flattenVisible(index, expanded, (node) =>
    !visibility.active || !isolate ? true : visibility.visible.has(node.id),
  )

  const rowIndexById = new Map(rows.map((r, i) => [r.node.id, i]))
  const gw = gutterWidth(groups)

  // The chain from the root down to the selected node, drawn brighter than the
  // rest so a part six levels deep can be traced back to its subsystem.
  const selectedNode = selectedId == null ? undefined : index.byId.get(selectedId)
  const pathIds = new Set<number>(
    selectedNode ? [...ancestorIds(selectedNode), selectedNode.id] : [],
  )

  // Which lanes each node sits on, so the row can show its own little swatches.
  const lanesByNode = new Map<number, ConnectionGroup[]>()
  for (const group of groups) {
    for (const id of group.nodeIds) {
      if (!rowIndexById.has(id)) continue
      const list = lanesByNode.get(id)
      if (list) list.push(group)
      else lanesByNode.set(id, [group])
    }
  }

  return (
    <div className="tree" role="tree" aria-label="Part hierarchy">
      <div
        className="tree-inner"
        style={
          {
            '--row-h': `${ROW_H}px`,
            '--conn-gutter': `${gw}px`,
          } as CSSProperties
        }
      >
        {rows.map((row) => {
          const node = row.node
          const kids = childrenOf(index, node.id)
          const isOpen = expanded.has(node.id)
          const tags = tagsOf(index, node.id)
          const fileCount = index.attachmentCounts.get(node.id) ?? 0
          const lanes = lanesByNode.get(node.id) ?? []

          let stateClass = ''
          if (visibility.active) {
            if (visibility.matched.has(node.id)) stateClass = 'is-match'
            else if (isolate) stateClass = 'is-context'
            else stateClass = 'dimmed'
          }

          return (
            <div
              key={node.id}
              className={[
                'row',
                stateClass,
                node.id === selectedId ? 'selected' : '',
                node.id === dragId ? 'dragging' : '',
                node.id === dropId ? 'drop-target' : '',
                lanes.length ? 'connected' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              role="treeitem"
              aria-expanded={kids.length ? isOpen : undefined}
              aria-selected={node.id === selectedId}
              tabIndex={0}
              onClick={() => onSelect(node.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onSelect(node.id)
                }
              }}
              onContextMenu={(e) => {
                e.preventDefault()
                onContextMenu(node, e.clientX, e.clientY)
              }}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('text/plain', String(node.id))
                e.dataTransfer.effectAllowed = 'move'
                setDragId(node.id)
              }}
              onDragEnd={() => {
                setDragId(null)
                setDropId(null)
              }}
              onDragOver={(e) => {
                if (dragId === node.id) return
                e.preventDefault()
                e.dataTransfer.dropEffect = 'move'
                setDropId(node.id)
              }}
              onDragLeave={() => setDropId((cur) => (cur === node.id ? null : cur))}
              onDrop={(e) => {
                e.preventDefault()
                setDropId(null)
                const draggedId = Number(e.dataTransfer.getData('text/plain'))
                if (draggedId && draggedId !== node.id) onMove(draggedId, node.id)
              }}
            >
              <TreeEdges row={row} onPath={pathIds.has(node.id)} />

              <button
                type="button"
                className={['twisty', kids.length ? '' : 'leaf', isOpen ? 'open' : '']
                  .filter(Boolean)
                  .join(' ')}
                aria-label={isOpen ? `Collapse ${node.name}` : `Expand ${node.name}`}
                tabIndex={-1}
                onClick={(e) => {
                  e.stopPropagation()
                  if (kids.length) onToggle(node.id)
                }}
              >
                ▶
              </button>

              <span
                className="status-pip"
                style={{ background: STATUS_COLORS[node.status] }}
                title={STATUS_LABELS[node.status]}
              />

              {node.node_type !== 'part' && (
                <span className="node-type-badge" data-type={node.node_type} title={node.node_type}>
                  {node.node_type.slice(0, 4)}
                </span>
              )}

              <span className="node-name">{node.name}</span>
              {node.part_number && <span className="node-pn">{node.part_number}</span>}
              {node.quantity > 1 && <span className="node-qty">{`x${node.quantity}`}</span>}

              <button
                type="button"
                className="row-add"
                title="Add a child node"
                aria-label={`Add a child under ${node.name}`}
                tabIndex={-1}
                onClick={(e) => {
                  e.stopPropagation()
                  onAddChild(node)
                }}
              >
                +
              </button>

              {/* Bridges the row to the connection gutter. Also the flex
                  spacer that pushes the tag dots right, so an unconnected row
                  lays out exactly as before. */}
              <span
                className="row-leader"
                style={lanes.length ? ({ '--leader': lanes[0].color } as CSSProperties) : undefined}
                aria-hidden="true"
              />

              <span className="row-tags">
                {fileCount > 0 && <span className="file-pip">{`📎${fileCount}`}</span>}
                {tags.slice(0, 6).map((tag) => (
                  <span
                    key={tag.tag_id}
                    className={`tag-dot${tag.inherited ? ' inherited' : ''}`}
                    style={{ background: tag.color }}
                    title={tag.inherited ? `${tag.name} (inherited)` : tag.name}
                  />
                ))}
              </span>
            </div>
          )
        })}

        {groups.length > 0 && (
          <ConnectionGutter
            groups={groups}
            rowIndexById={rowIndexById}
            rowCount={rows.length}
            width={gw}
          />
        )}
      </div>
    </div>
  )
}

/**
 * The drawn hierarchy, one SVG per row.
 *
 * Ancestor columns are plain risers; the row's own edge is a rounded elbow when
 * it is the last child and a tee when it is not. Keeping the geometry row-local
 * rather than one canvas behind everything means nothing has to know the total
 * row count, so expanding a branch cannot knock the lines out of register.
 *
 * A root gets an empty layer rather than none at all — it still has to occupy
 * its column so its children's risers line up under it.
 */
function TreeEdges({ row, onPath }: { row: TreeRow; onPath: boolean }) {
  const depth = row.ancestorHasNext.length
  const width = (depth + 1) * INDENT
  const mid = ROW_H / 2
  const ex = depth * INDENT + INDENT / 2
  const stroke = onPath ? 'var(--tree-edge-strong)' : 'var(--tree-edge)'
  const w = onPath ? 1.6 : 1

  return (
    <svg
      className="tree-edges"
      width={width}
      height={ROW_H}
      viewBox={`0 0 ${width} ${ROW_H}`}
      aria-hidden="true"
    >
      {row.ancestorHasNext.map((hasNext, i) =>
        hasNext ? (
          <line
            key={i}
            x1={i * INDENT + INDENT / 2}
            y1={0}
            x2={i * INDENT + INDENT / 2}
            y2={ROW_H}
            stroke="var(--tree-edge)"
            strokeWidth={1}
          />
        ) : null,
      )}

      {depth > 0 &&
        (row.isLast ? (
          <path
            d={`M ${ex} 0 V ${mid - ELBOW_R} Q ${ex} ${mid} ${ex + ELBOW_R} ${mid} H ${width}`}
            fill="none"
            stroke={stroke}
            strokeWidth={w}
            strokeLinecap="round"
          />
        ) : (
          <>
            <line x1={ex} y1={0} x2={ex} y2={ROW_H} stroke={stroke} strokeWidth={w} />
            <line
              x1={ex}
              y1={mid}
              x2={width}
              y2={mid}
              stroke={stroke}
              strokeWidth={w}
              strokeLinecap="round"
            />
          </>
        ))}
    </svg>
  )
}

/**
 * The right-hand gutter.
 *
 * One vertical lane per selected value. Every node carrying that value gets a
 * dot on the lane and a faint leader back to its row, and the dots are joined
 * top to bottom. Because it is indexed by row position rather than by tree
 * position, a link between a bolt under Brakes and a bolt under Steering is
 * just a straight line — which is the whole point.
 */
function ConnectionGutter({
  groups,
  rowIndexById,
  rowCount,
  width,
}: {
  groups: ConnectionGroup[]
  rowIndexById: Map<number, number>
  rowCount: number
  width: number
}) {
  const height = rowCount * ROW_H

  return (
    <svg
      className="conn-gutter"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      {groups.map((group) => {
        const x = GUTTER_PAD + group.lane * LANE_WIDTH + LANE_WIDTH / 2
        const ys = group.nodeIds
          .map((id) => rowIndexById.get(id))
          .filter((i): i is number => i !== undefined)
          .map((i) => i * ROW_H + ROW_H / 2)
          .sort((a, b) => a - b)

        if (ys.length === 0) return null

        return (
          <g key={group.key} stroke={group.color} fill={group.color}>
            {/* Picks up where the row's own dotted leader stops, with the
                same dash, so the two read as one line into the lane. */}
            {ys.map((y) => (
              <line
                key={`l${y}`}
                x1={0}
                y1={y}
                x2={x}
                y2={y}
                strokeWidth={1}
                strokeDasharray="3 4"
                opacity={0.55}
              />
            ))}
            {/* the spine joining every member of this value */}
            {ys.length > 1 && (
              <line
                x1={x}
                y1={ys[0]}
                x2={x}
                y2={ys[ys.length - 1]}
                strokeWidth={1.75}
                strokeLinecap="round"
              />
            )}
            {ys.map((y) => (
              <circle key={`d${y}`} cx={x} cy={y} r={3.5} stroke="none" />
            ))}
          </g>
        )
      })}
    </svg>
  )
}
