import type {
  Attachment,
  Countdown,
  LearnGroup,
  LearnIcon,
  LearnImage,
  LearnPage,
  LearnReference,
  LearnSection,
  Member,
  MfgPart,
  MfgStatus,
  Milestone,
  DeleteResult,
  NodeDetail,
  OrderStatus,
  ProjectOut,
  ProjectSummary,
  PurchaseRequest,
  Resource,
  ResourceKind,
  Status,
  Tag,
  TreeNode,
  TreeResponse,
} from './types'

/** Thrown for any non-2xx response, carrying the API's own message. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

interface ValidationItem {
  loc?: (string | number)[]
  msg?: string
}

/**
 * A session that expired mid-use, or a signed-out visitor. Send them to the
 * login page and come straight back to where they were.
 *
 * Returns a promise that never settles on purpose: the page is already
 * navigating away, and resolving would flash an error toast on the way out.
 */
function toLogin(): Promise<never> {
  const next = encodeURIComponent(window.location.pathname + window.location.search)
  window.location.href = `/login?next=${next}`
  return new Promise<never>(() => {})
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, options)
  if (res.status === 401) return toLogin()
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body: unknown = await res.json()
      const detail = (body as { detail?: unknown }).detail
      if (Array.isArray(detail)) {
        // FastAPI validation errors arrive as a list of {loc, msg}.
        message = (detail as ValidationItem[])
          .map((d) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? ''}`)
          .join('; ')
      } else if (typeof detail === 'string') {
        message = detail
      }
    } catch {
      // Non-JSON error body — keep the status line.
    }
    throw new ApiError(message, res.status)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function withJson<T>(method: string) {
  return (url: string, body: unknown): Promise<T> =>
    request<T>(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
}

export interface NodeCreatePayload {
  project_id: number
  parent_id: number | null
  name: string
  node_type?: string
  status?: Status
}

export type AuthMode = 'cloudflare' | 'password' | 'none'

export const api = {
  health: () => request<{ status: string; team: string; auth_mode: AuthMode }>('/api/health'),
  me: () => request<Member>('/api/auth/me'),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  /** Set your own display name. Self-service — no admin needed. */
  updateProfile: (payload: { name: string; subteam?: string | null }) =>
    withJson<Member>('PATCH')('/api/auth/me', payload),

  /** The roster. Readable by anyone signed in — the assignee dropdown needs it. */
  listMembers: () => request<Member[]>('/api/members?include_inactive=true'),

  /**
   * Promote or demote a teammate. Admin-only, and the server refuses to demote
   * the last remaining admin, so the UI can offer the button and let the API
   * be the authority rather than duplicating the rule and drifting from it.
   */
  setMemberAdmin: (id: number, isAdmin: boolean) =>
    withJson<Member>('PATCH')(`/api/members/${id}/admin`, { is_admin: isAdmin }),

  /** The timeline for one tree, earliest goal first. */
  listMilestones: (projectId: number) =>
    request<Milestone[]>(`/api/milestones?project_id=${projectId}`),

  /** Admin only -- adding a goal is planning. */
  createMilestone: (payload: {
    project_id: number
    title: string
    due_date: string
    detail?: string | null
    priority?: Milestone['priority']
    kind?: Milestone['kind']
    owner_id?: number | null
    node_id?: number | null
  }) => withJson<Milestone>('POST')('/api/milestones', payload),

  /**
   * Any member, including ticking it off: whoever finished the work knows it
   * is finished, and needing a lead to tick a box is how a timeline goes stale.
   */
  updateMilestone: (
    id: number,
    payload: Partial<Pick<Milestone, 'title' | 'due_date' | 'detail' | 'priority' | 'kind' | 'owner_id' | 'node_id' | 'done'>>,
  ) => withJson<Milestone>('PATCH')(`/api/milestones/${id}`, payload),

  deleteMilestone: (id: number) =>
    request<void>(`/api/milestones/${id}`, { method: 'DELETE' }),

  /** The shop's cut list for one tree, ordered by subsystem then name. */
  listMfgParts: (projectId: number) =>
    request<MfgPart[]>(`/api/mfg-parts?project_id=${projectId}`),

  /** Admin only — deciding what gets made is planning. */
  createMfgPart: (payload: {
    project_id: number
    name: string
    subsystem?: string | null
    status?: MfgStatus
    notes?: string | null
    assignee_id?: number | null
  }) => withJson<MfgPart>('POST')('/api/mfg-parts', payload),

  /** Any member: the person at the bandsaw marks it done and writes the notes. */
  updateMfgPart: (
    id: number,
    payload: Partial<
      Pick<MfgPart, 'name' | 'subsystem' | 'status' | 'notes' | 'assignee_id' | 'links'>
    >,
  ) => withJson<MfgPart>('PATCH')(`/api/mfg-parts/${id}`, payload),

  deleteMfgPart: (id: number) =>
    request<void>(`/api/mfg-parts/${id}`, { method: 'DELETE' }),

  /**
   * Attach or replace the drawing. PUT because there is exactly one.
   * Do NOT set Content-Type — the browser has to add the multipart boundary.
   */
  uploadDrawing: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<MfgPart>(`/api/mfg-parts/${id}/drawing`, { method: 'PUT', body: form })
  },

  clearDrawing: (id: number) =>
    request<MfgPart>(`/api/mfg-parts/${id}/drawing`, { method: 'DELETE' }),

  /**
   * Where to point an <img>, an <iframe> or a download link.
   *
   * Not a fetch: the browser loads this itself and decides whether to render
   * or save from the response's Content-Disposition. `download` flips that.
   */
  drawingUrl: (id: number, download = false) =>
    `/api/mfg-parts/${id}/drawing${download ? '?download=1' : ''}`,

  listProjects: () => request<ProjectSummary[]>('/api/projects'),

  createProject: (payload: {
    name: string
    season?: string | null
    template: 'blank' | 'baja_standard'
  }) => withJson<ProjectOut>('POST')('/api/projects', payload),

  cloneProject: (payload: {
    name: string
    season?: string | null
    source_project_id: number
    reset_status?: Status
  }) => withJson<ProjectOut>('POST')('/api/projects/clone', payload),

  deleteProject: (id: number) =>
    request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  getTree: (projectId: number) => request<TreeResponse>(`/api/projects/${projectId}/tree`),

  getNode: (id: number) => request<NodeDetail>(`/api/nodes/${id}`),

  createNode: (payload: NodeCreatePayload) => withJson<NodeDetail>('POST')('/api/nodes', payload),

  updateNode: (id: number, payload: Partial<TreeNode>) =>
    withJson<NodeDetail>('PATCH')(`/api/nodes/${id}`, payload),

  moveNode: (id: number, newParentId: number | null) =>
    withJson<NodeDetail>('POST')(`/api/nodes/${id}/move`, { new_parent_id: newParentId }),

  duplicateNode: (id: number, name?: string) =>
    withJson<NodeDetail>('POST')(`/api/nodes/${id}/duplicate`, { name }),

  deleteNode: (id: number) => request<DeleteResult>(`/api/nodes/${id}`, { method: 'DELETE' }),

  listTags: () => request<Tag[]>('/api/tags'),

  createTag: (payload: { name: string; color?: string; category?: string | null }) =>
    withJson<Tag>('POST')('/api/tags', payload),

  addTag: (nodeId: number, tagId: number, cascade: boolean) =>
    withJson<unknown>('POST')(`/api/nodes/${nodeId}/tags`, { tag_id: tagId, cascade }),

  removeTag: (nodeId: number, tagId: number) =>
    request<void>(`/api/nodes/${nodeId}/tags/${tagId}`, { method: 'DELETE' }),

  /**
   * Multipart upload. Do NOT set Content-Type by hand — the browser has to add
   * the multipart boundary itself.
   */
  upload: (nodeId: number, file: File) => {
    const form = new FormData()
    form.append('node_id', String(nodeId))
    form.append('file', file)
    return request<Attachment>('/api/attachments', { method: 'POST', body: form })
  },

  deleteAttachment: (id: number) =>
    request<void>(`/api/attachments/${id}`, { method: 'DELETE' }),

  /* ------------------------------------------------------------- Learn */
  // Team-wide, not per tree: no project_id anywhere below.

  /** Every section with its page titles -- the whole Learn index. */
  getLearn: () => request<{ sections: LearnSection[] }>('/api/learn'),

  /** Admin only. */
  createLearnSection: (payload: {
    title: string
    summary?: string | null
    group: LearnGroup
    icon: LearnIcon
  }) => withJson<LearnSection>('POST')('/api/learn/sections', payload),

  /** Admin only, like every Learn write: these pages are team guidance. */
  updateLearnSection: (
    id: number,
    payload: Partial<Pick<LearnSection, 'title' | 'summary' | 'group' | 'icon'>>,
  ) => withJson<LearnSection>('PATCH')(`/api/learn/sections/${id}`, payload),

  /** Swap with a neighbour. Returns the whole index, already reordered. */
  moveLearnSection: (id: number, direction: 'up' | 'down') =>
    withJson<{ sections: LearnSection[] }>('POST')(`/api/learn/sections/${id}/move`, { direction }),

  /** Admin only. Takes its pages and pictures with it. */
  deleteLearnSection: (id: number) =>
    request<void>(`/api/learn/sections/${id}`, { method: 'DELETE' }),

  /** The card's render. Do NOT set Content-Type -- the browser adds the boundary. */
  setLearnSectionImage: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<LearnSection>(`/api/learn/sections/${id}/image`, { method: 'PUT', body: form })
  },

  clearLearnSectionImage: (id: number) =>
    request<LearnSection>(`/api/learn/sections/${id}/image`, { method: 'DELETE' }),

  getLearnPage: (id: number) => request<LearnPage>(`/api/learn/pages/${id}`),

  /** Admin only. */
  createLearnPage: (sectionId: number, title: string) =>
    withJson<LearnPage>('POST')('/api/learn/pages', { section_id: sectionId, title }),

  /**
   * Save an edit. `base_version` is the version the editor opened; if someone
   * else saved in between, this rejects with an ApiError whose status is 409
   * and nothing is overwritten.
   */
  updateLearnPage: (
    id: number,
    payload: {
      title?: string
      body?: string
      references?: LearnReference[]
      base_version: number
    },
  ) => withJson<LearnPage>('PATCH')(`/api/learn/pages/${id}`, payload),

  moveLearnPage: (id: number, direction: 'up' | 'down') =>
    withJson<{ sections: LearnSection[] }>('POST')(`/api/learn/pages/${id}/move`, { direction }),

  /** Admin only. */
  deleteLearnPage: (id: number) => request<void>(`/api/learn/pages/${id}`, { method: 'DELETE' }),

  /** A picture for a writeup or a reference card. Returns the URL to use. */
  uploadLearnImage: (sectionId: number, file: File, pageId?: number) => {
    const form = new FormData()
    form.append('section_id', String(sectionId))
    if (pageId != null) form.append('page_id', String(pageId))
    form.append('file', file)
    return request<LearnImage>('/api/learn/images', { method: 'POST', body: form })
  },

  /* ------------------------------------------------------------ Orders */

  /** One tree's purchase requests, newest first. */
  listOrders: (projectId: number) =>
    request<PurchaseRequest[]>(`/api/purchase-requests?project_id=${projectId}`),

  /** Any member. The server records who asked from the signed-in identity. */
  createOrder: (payload: {
    project_id: number
    item: string
    vendor?: string | null
    url?: string | null
    part_number?: string | null
    quantity?: number
    unit_cost_cents?: number | null
    notes?: string | null
    subsystem?: string | null
    needed_by?: string | null
  }) => withJson<PurchaseRequest>('POST')('/api/purchase-requests', payload),

  /**
   * Members: their own request while it waits, cancelling it, or marking an
   * order received. Everything else is for leads -- the server says which.
   */
  updateOrder: (
    id: number,
    payload: Partial<
      Pick<
        PurchaseRequest,
        | 'item'
        | 'vendor'
        | 'url'
        | 'part_number'
        | 'quantity'
        | 'unit_cost_cents'
        | 'notes'
        | 'subsystem'
        | 'needed_by'
        | 'order_number'
        | 'tracking_number'
      >
    > & { status?: OrderStatus },
  ) => withJson<PurchaseRequest>('PATCH')(`/api/purchase-requests/${id}`, payload),

  /** Admin only. Requesters withdraw by cancelling, which keeps the record. */
  deleteOrder: (id: number) =>
    request<void>(`/api/purchase-requests/${id}`, { method: 'DELETE' }),

  /* --------------------------------------------------------- Resources */
  // Team-wide: no project id. Anyone adds; the finder or an admin changes it.

  listResources: () => request<Resource[]>('/api/resources'),

  createResource: (payload: {
    title: string
    url?: string | null
    kind?: ResourceKind
    topic?: string | null
    notes?: string | null
  }) => withJson<Resource>('POST')('/api/resources', payload),

  updateResource: (
    id: number,
    payload: Partial<Pick<Resource, 'title' | 'url' | 'kind' | 'topic' | 'notes'>>,
  ) => withJson<Resource>('PATCH')(`/api/resources/${id}`, payload),

  deleteResource: (id: number) => request<void>(`/api/resources/${id}`, { method: 'DELETE' }),

  /** Attach or replace the file. Do NOT set Content-Type -- the browser adds the boundary. */
  uploadResourceFile: (id: number, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<Resource>(`/api/resources/${id}/file`, { method: 'PUT', body: form })
  },

  clearResourceFile: (id: number) =>
    request<Resource>(`/api/resources/${id}/file`, { method: 'DELETE' }),

  /** For a link or an <iframe>, not a fetch. `download` forces a save. */
  resourceFileUrl: (id: number, download = false) =>
    `/api/resources/${id}/file${download ? '?download=1' : ''}`,

  /* --------------------------------------------------------- Countdown */

  getCountdown: () => request<Countdown>('/api/countdown'),

  /** Admin only. `at` must carry a timezone -- send an ISO instant. */
  setCountdown: (payload: { label: string; at: string }) =>
    withJson<Countdown>('PUT')('/api/countdown', payload),

  clearCountdown: () => request<void>('/api/countdown', { method: 'DELETE' }),
}
