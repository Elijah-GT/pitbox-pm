import type { EffectiveTag, TreeNode, TreeResponse } from '../api/types'

/**
 * Indexes derived once per tree fetch.
 *
 * The whole tree arrives flat in a single response, so we build the parent/child
 * map here and keep everything in memory. That is what makes filtering and
 * expand/collapse instant — no request per keystroke, no lazy branch loading.
 */
export interface TreeIndex {
  nodes: TreeNode[]
  byId: Map<number, TreeNode>
  childrenOf: Map<number | 'root', TreeNode[]>
  tagsByNode: Map<number, EffectiveTag[]>
  attachmentCounts: Map<number, number>
}

export const ROOT = 'root' as const

export function buildIndex(payload: TreeResponse): TreeIndex {
  const byId = new Map<number, TreeNode>()
  const childrenOf = new Map<number | 'root', TreeNode[]>()

  for (const node of payload.nodes) {
    byId.set(node.id, node)
    const key: number | 'root' = node.parent_id ?? ROOT
    const bucket = childrenOf.get(key)
    if (bucket) bucket.push(node)
    else childrenOf.set(key, [node])
  }

  // JSON object keys are strings; normalize to numbers so lookups by node.id work.
  const tagsByNode = new Map<number, EffectiveTag[]>(
    Object.entries(payload.tags_by_node).map(([k, v]) => [Number(k), v]),
  )
  const attachmentCounts = new Map<number, number>(
    Object.entries(payload.attachment_counts).map(([k, v]) => [Number(k), v]),
  )

  return { nodes: payload.nodes, byId, childrenOf, tagsByNode, attachmentCounts }
}

export function childrenOf(index: TreeIndex, id: number | null): TreeNode[] {
  return index.childrenOf.get(id ?? ROOT) ?? []
}

export function rootNodes(index: TreeIndex): TreeNode[] {
  return index.childrenOf.get(ROOT) ?? []
}

export function tagsOf(index: TreeIndex, id: number): EffectiveTag[] {
  return index.tagsByNode.get(id) ?? []
}

/**
 * Ancestor ids, root first. No traversal needed — the materialized path already
 * encodes them: '/1/7/23/' → [1, 7]. The last segment is the node's own id.
 */
export function ancestorIds(node: TreeNode): number[] {
  const parts = node.path.split('/').filter(Boolean)
  return parts.slice(0, -1).map(Number)
}

/**
 * A row ready to draw, carrying the guide-line shape for the left gutter.
 *
 * `ancestorHasNext[d]` says whether the ancestor at depth d still has siblings
 * below it — that is what decides whether that column carries a riser or is
 * left blank. `isLast` picks a rounded elbow over a tee for the node's own edge.
 * TreeEdges in TreeView.tsx turns both into SVG.
 *
 * Both are computed over the RENDERED set, not the full tree: if a filter hides
 * the last three children of a branch, the last surviving child must get the
 * '└──' corner or the lines dangle into nothing.
 */
export interface TreeRow {
  node: TreeNode
  isLast: boolean
  ancestorHasNext: boolean[]
}

/** Depth-first order for rendering, honouring sibling position. */
export function flattenVisible(
  index: TreeIndex,
  expanded: ReadonlySet<number>,
  shouldRender: (node: TreeNode) => boolean,
): TreeRow[] {
  const out: TreeRow[] = []

  const walk = (nodes: TreeNode[], ancestorHasNext: boolean[]) => {
    const shown = nodes.filter(shouldRender)
    shown.forEach((node, i) => {
      const isLast = i === shown.length - 1
      out.push({ node, isLast, ancestorHasNext })
      const kids = childrenOf(index, node.id)
      if (kids.length && expanded.has(node.id)) {
        // Children continue this node's column only while it has siblings left.
        walk(kids, [...ancestorHasNext, !isLast])
      }
    })
  }

  walk(rootNodes(index), [])
  return out
}
