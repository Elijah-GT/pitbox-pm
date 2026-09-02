import type {
  Attachment,
  Member,
  DeleteResult,
  NodeDetail,
  ProjectOut,
  ProjectSummary,
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
}
