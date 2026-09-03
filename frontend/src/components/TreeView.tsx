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
import { childrenOf, flattenVisible, guidePrefix, tagsOf, type TreeIndex } from '../lib/tree'

/**
 * Fixed row height. The connection gutter positions everything by row index
 * rather than by measuring the DOM, so this constant and the CSS must agree —
 * which is why the component sets --row-h from here instead of the stylesheet
 * declaring its own number.
 */
export const ROW_H = 26

interface Props {
  index: TreeIndex
  visibility: Visibility
  expanded: ReadonlySet<number>
  selectedId: number | null
  isolate: boolean
  groups: ConnectionGroup[]
  /** Any signed-in member: may drag to re-parent and open the row menu. */
  canEdit: boolean
  /** Admin: may add a child straight from a row. */
  isAdmin: boolean
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
  canEdit,
  isAdmin,
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
                // Members get the menu too -- it carries Rename for them. With
                // nothing to offer, the browser's own menu is more use.
                if (!canEdit) return
                e.preventDefault()
                onContextMenu(node, e.clientX, e.clientY)
              }}
              draggable={canEdit}
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
                // Rows are not draggable without write access, but a file
                // dragged in from the desktop still fires this. Bail, or a
                // member who cannot re-parent anything watches rows light up
                // as drop targets.
                if (!canEdit || dragId === node.id) return
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
              {/* Hierarchy guides — the DOS `tree` look, monospaced so the
                  columns line up exactly down the whole list. */}
              <span className="guides" aria-hidden="true">
                {guidePrefix(row)}
              </span>

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

              {isAdmin && (
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
              )}

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
            {/* leader from the row to its lane */}
            {ys.map((y) => (
              <line
                key={`l${y}`}
                x1={0}
                y1={y}
                x2={x}
                y2={y}
                strokeWidth={1}
                opacity={0.28}
              />
            ))}
            {/* the spine joining every member of this value */}
            {ys.length > 1 && (
              <line x1={x} y1={ys[0]} x2={x} y2={ys[ys.length - 1]} strokeWidth={1.75} />
            )}
            {ys.map((y) => (
              <circle key={`d${y}`} cx={x} cy={y} r={3} stroke="none" />
            ))}
          </g>
        )
      })}
    </svg>
  )
}
