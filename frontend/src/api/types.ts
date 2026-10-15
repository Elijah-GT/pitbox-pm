// Mirrors app/schemas.py. When you change a Pydantic model, change it here too.
// The status list is checked against the backend by a test, since it lives in
// three places (schemas.py, here, and static/js/treeview.js).

export type NodeType = 'vehicle' | 'subsystem' | 'assembly' | 'part'

export type Status =
  | 'concept'
  | 'design'
  | 'in_review'
  | 'ordered'
  | 'in_fabrication'
  | 'assembled'
  | 'not_installed'
  | 'installed'

export type Sourcing = 'make' | 'buy' | 'na'

export interface ProjectOut {
  id: number
  name: string
  slug: string
  season: string | null
  description: string | null
  is_archived: boolean
  created_at: string
  updated_at: string
}

export interface ProjectSummary extends ProjectOut {
  node_count: number
  attachment_count: number
}

export interface TreeNode {
  id: number
  project_id: number
  parent_id: number | null
  path: string
  depth: number
  position: number
  name: string
  node_type: NodeType
  part_number: string | null
  status: Status
  assignee_id: number | null
  description: string | null
  quantity: number
  sourcing: Sourcing
  material: string | null
  mass_g: number | null
  cost_cents: number | null
  vendor: string | null
  lead_time_days: number | null
  extra: Record<string, unknown>
  created_at: string
  updated_at: string
}

/** A dated goal on the project timeline. Not a node -- it has no place in the
 *  assembly tree, but it has the one thing no node has: a date. */
/**
 * How hard a goal's date is. "sae" is not a severity but an authority: Baja
 * SAE sets those dates and the team cannot move them.
 */
export type GoalPriority = 'sae' | 'critical' | 'normal' | 'low'

/** Which half of the season a goal belongs to. */
export type GoalKind = 'design' | 'manufacturing' | 'other'

export interface Milestone {
  id: number
  project_id: number
  title: string
  detail: string | null
  /** ISO calendar date, "2026-02-12". A deadline is a day, not an instant. */
  due_date: string
  priority: GoalPriority
  kind: GoalKind
  done: boolean
  done_at: string | null
  owner_id: number | null
  /** Optional link to the part or subsystem this goal is about. */
  node_id: number | null
}

/** Where a shop-floor part has got to. */
export type MfgStatus = 'todo' | 'in_progress' | 'done'

/**
 * One row of the shop's cut list. Flat on purpose — the tree says what the car
 * is made of, this says what has to be made this week, and they are not the
 * same list.
 */
/**
 * A related link on a part: the part in Onshape, a vendor page, a bend table.
 * The server allows http and https only — these become real hrefs.
 */
export interface MfgLink {
  label: string | null
  url: string
}

export interface MfgPart {
  id: number
  project_id: number
  /** Meant to match the part's name in Onshape exactly. That string is the join. */
  name: string
  subsystem: string | null
  status: MfgStatus
  notes: string | null
  assignee_id: number | null
  links: MfgLink[]

  /** The drawing. Its storage address is deliberately not exposed. */
  has_drawing: boolean
  drawing_filename: string | null
  drawing_content_type: string | null
  drawing_size_bytes: number | null
  drawing_uploaded_at: string | null
}

export interface EffectiveTag {
  tag_id: number
  slug: string
  name: string
  color: string
  category: string | null
  cascade: boolean
  /** True when the tag comes from a cascading tag on an ancestor, not from here. */
  inherited: boolean
  source_node_id: number
}

export interface Attachment {
  id: number
  node_id: number
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  kind: string
  version: number
  is_current: boolean
  notes: string | null
  uploaded_by_id: number | null
  uploaded_at: string
}

export interface NodeDetail extends TreeNode {
  tags: EffectiveTag[]
  attachments: Attachment[]
  ancestor_ids: number[]
  child_count: number
  descendant_count: number
  rollup_cost_cents: number
  rollup_mass_g: number
}

export interface Tag {
  id: number
  name: string
  slug: string
  color: string
  category: string | null
  description: string | null
  node_count: number
}

export interface Member {
  id: number
  name: string
  email: string | null
  subteam: string | null
  role: string | null
  is_active: boolean
  /** Admins manage the roster. Absent on older payloads, so default false. */
  is_admin?: boolean
  /** Whether this member can sign in at all. The hash never leaves the server. */
  has_password?: boolean
  /** False when the name was derived from an email rather than typed by them. */
  name_confirmed?: boolean
}

export interface TreeResponse {
  project: ProjectOut
  nodes: TreeNode[]
  /** Keyed by node id — JSON object keys arrive as strings. */
  tags_by_node: Record<string, EffectiveTag[]>
  attachment_counts: Record<string, number>
  tags: Tag[]
  members: Member[]
}

export interface DeleteResult {
  deleted_node_id: number
  deleted_count: number
}
