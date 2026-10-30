import { useEffect, useMemo, useState, type FormEvent } from 'react'

import { api } from '../api/client'
import type { Resource, ResourceKind } from '../api/types'
import { humanSize } from '../lib/format'
import { safeHref } from '../lib/markdown'
import { Markdown } from './Markdown'

const KIND_LABELS: Record<ResourceKind, string> = {
  article: 'Article',
  paper: 'Paper',
  report: 'Design report',
  video: 'Video',
  datasheet: 'Datasheet',
  forum: 'Forum thread',
  other: 'Other',
}
const KIND_ORDER = Object.keys(KIND_LABELS) as ResourceKind[]

interface Props {
  /** Decides which resources are "yours" to edit. */
  currentUserId: number | null
  isAdmin: boolean
  /** Suggestions for the topic box: this car's subsystems, if a tree is open. */
  topicSuggestions: string[]
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * Resources: research the team has found -- design reports, papers, videos,
 * datasheets -- with a note on why each one is worth reading.
 *
 * Not Learn. Learn is the team's guidance, kept by leads; this is the pile of
 * research behind it, and anyone can add to it. Whoever added something can
 * edit or remove it, and so can an admin (app/routers/resources.py). The
 * buttons here mirror that rule but grant nothing.
 */
export function ResourcesView({ currentUserId, isAdmin, topicSuggestions, onError, onToast }: Props) {
  const [rows, setRows] = useState<Resource[] | null>(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<ResourceKind | 'all'>('all')
  const [topic, setTopic] = useState<string>('all')
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    api
      .listResources()
      .then((list) => {
        if (alive) setRows(list)
      })
      .catch((err: unknown) => {
        if (alive) onError(err)
      })
    return () => {
      alive = false
    }
  }, [onError])

  const canChange = (r: Resource) =>
    isAdmin || (currentUserId != null && r.added_by_id === currentUserId)

  // Topics already in use first, then this car's subsystems, without repeats.
  const topics = useMemo(() => {
    const used = new Set((rows ?? []).map((r) => r.topic).filter((t): t is string => Boolean(t)))
    return [...used].sort((a, b) => a.localeCompare(b))
  }, [rows])
  const suggestions = useMemo(
    () => [...new Set([...topics, ...topicSuggestions])].sort((a, b) => a.localeCompare(b)),
    [topics, topicSuggestions],
  )

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (rows ?? []).filter(
      (r) =>
        (kind === 'all' || r.kind === kind) &&
        (topic === 'all' || r.topic === topic) &&
        (!q ||
          [r.title, r.notes, r.topic, r.url, r.file_name, r.added_by_name].some((f) =>
            f?.toLowerCase().includes(q),
          )),
    )
  }, [rows, query, kind, topic])

  const replace = (row: Resource) =>
    setRows((prev) => (prev ? prev.map((r) => (r.id === row.id ? row : r)) : prev))

  async function remove(r: Resource) {
    if (!confirm(`Remove "${r.title}" from Resources?`)) return
    try {
      await api.deleteResource(r.id)
      setRows((prev) => (prev ? prev.filter((x) => x.id !== r.id) : prev))
      onToast('Resource removed')
    } catch (err) {
      onError(err)
    }
  }

  if (!rows) return <p className="loading">Loading resources…</p>

  return (
    <section className="shop resources" aria-label="Resources">
      <div className="shop-head">
        <h2>Resources</h2>
        <span className="shop-stats">
          {rows.length} saved
        </span>
      </div>
      <p className="resources-blurb">
        Research the team has found — other teams’ design reports, papers, videos, datasheets.
        Anyone can add to it; say in the notes why it is worth reading.
      </p>

      {adding ? (
        <ResourceForm
          heading="Add a resource"
          submitLabel="Add"
          suggestions={suggestions}
          onCancel={() => setAdding(false)}
          onSubmit={async (fields, file) => {
            let made = await api.createResource(fields)
            if (file) made = await api.uploadResourceFile(made.id, file)
            setRows((prev) => [made, ...(prev ?? [])])
            setAdding(false)
            onToast('Resource added')
          }}
          onError={onError}
        />
      ) : (
        <div className="orders-bar">
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            + Add a resource
          </button>
          <select
            className="input"
            aria-label="Kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as ResourceKind | 'all')}
          >
            <option value="all">Every kind</option>
            {KIND_ORDER.map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
          <select className="input" aria-label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
            <option value="all">Every topic</option>
            {topics.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            className="input search"
            type="search"
            placeholder="Search titles, notes, who added it…"
            aria-label="Search resources"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      {rows.length === 0 && (
        <p className="shop-empty">
          Nothing saved yet. Found a useful design report or video? Use <b>Add a resource</b> so the
          next person does not have to find it again.
        </p>
      )}
      {rows.length > 0 && visible.length === 0 && <p className="shop-empty">Nothing matches.</p>}

      <div className="res-grid">
        {visible.map((r) =>
          editingId === r.id ? (
            <ResourceForm
              key={r.id}
              heading="Edit resource"
              submitLabel="Save"
              initial={r}
              suggestions={suggestions}
              onCancel={() => setEditingId(null)}
              onSubmit={async (fields, file, dropFile) => {
                let saved = await api.updateResource(r.id, fields)
                if (file) saved = await api.uploadResourceFile(r.id, file)
                else if (dropFile) saved = await api.clearResourceFile(r.id)
                replace(saved)
                setEditingId(null)
                onToast('Resource updated')
              }}
              onError={onError}
            />
          ) : (
            <ResourceCard
              key={r.id}
              resource={r}
              canChange={canChange(r)}
              onEdit={() => setEditingId(r.id)}
              onRemove={() => void remove(r)}
            />
          ),
        )}
      </div>

      <datalist id="resource-topics">
        {suggestions.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
    </section>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function ResourceCard({
  resource: r, canChange, onEdit, onRemove,
}: {
  resource: Resource
  canChange: boolean
  onEdit: () => void
  onRemove: () => void
}) {
  // The server only stores http(s); vetted again because this becomes an href.
  const link = r.url ? safeHref(r.url) : null
  const added = new Date(r.created_at).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })

  return (
    <article className={`res-card kind-${r.kind}`}>
      <div className="res-top">
        <span className="res-kind">{KIND_LABELS[r.kind]}</span>
        {r.topic && <span className="res-topic">{r.topic}</span>}
      </div>
      <h3 className="res-title">
        {link?.external ? (
          <a href={link.href} target="_blank" rel="noopener noreferrer">
            {r.title} <span aria-hidden="true">↗</span>
          </a>
        ) : (
          r.title
        )}
      </h3>
      {link?.external && <div className="res-host">{hostOf(link.href)}</div>}
      {r.notes && (
        <div className="res-notes">
          <Markdown source={r.notes} />
        </div>
      )}
      {r.has_file && (
        <div className="res-file">
          <a href={api.resourceFileUrl(r.id)} target="_blank" rel="noopener noreferrer">
            {r.file_name}
          </a>
          {r.file_size_bytes != null && <span>{humanSize(r.file_size_bytes)}</span>}
          <a href={api.resourceFileUrl(r.id, true)}>Download</a>
        </div>
      )}
      <div className="res-foot">
        <span>
          Added by {r.added_by_name ?? 'a former member'} · {added}
        </span>
        {canChange && (
          <span className="res-actions">
            <button type="button" className="btn btn-sm btn-ghost" onClick={onEdit}>
              Edit
            </button>
            <button type="button" className="btn btn-sm btn-ghost btn-danger" onClick={onRemove}>
              Remove
            </button>
          </span>
        )}
      </div>
    </article>
  )
}

/** "example.com/x" -> "https://example.com/x". */
function withScheme(raw: string): string {
  const url = raw.trim()
  if (!url || /^[a-z][a-z0-9+.-]*:/i.test(url)) return url
  return `https://${url}`
}

interface ResourceFields {
  title: string
  url: string | null
  kind: ResourceKind
  topic: string | null
  notes: string | null
}

function ResourceForm({
  heading, submitLabel, initial, suggestions, onSubmit, onCancel, onError,
}: {
  heading: string
  submitLabel: string
  initial?: Resource
  suggestions: string[]
  /** `file` to attach or replace; `dropFile` to remove the current one. */
  onSubmit: (fields: ResourceFields, file: File | null, dropFile: boolean) => Promise<void>
  onCancel: () => void
  onError: (err: unknown) => void
}) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  const [kind, setKind] = useState<ResourceKind>(initial?.kind ?? 'article')
  const [topic, setTopic] = useState(initial?.topic ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [file, setFile] = useState<File | null>(null)
  const [dropFile, setDropFile] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!title.trim()) return setProblem('Give it a title — what is it?')
    setProblem(null)
    setBusy(true)
    try {
      await onSubmit(
        {
          title: title.trim(),
          url: withScheme(url) || null,
          kind,
          topic: topic.trim() || null,
          notes: notes.trim() || null,
        },
        file,
        dropFile,
      )
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="order-form res-form" onSubmit={(e) => void submit(e)}>
      <h3 className="shop-group-head">{heading}</h3>
      <div className="order-form-grid">
        <label className="span-2">
          Title
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Cornell Baja 2024 design report"
            maxLength={200}
            autoFocus
          />
        </label>
        <label className="span-2">
          Link
          <input
            className="input"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste the page, paper or video"
            inputMode="url"
          />
        </label>
        <label>
          Kind
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as ResourceKind)}>
            {KIND_ORDER.map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Topic
          <input
            className="input"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            list="resource-topics"
            placeholder={suggestions[0] ? `e.g. ${suggestions[0]}` : 'e.g. Suspension'}
            maxLength={80}
          />
        </label>
        <label className="span-2">
          File (optional)
          <input
            className="input"
            type="file"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setDropFile(false)
            }}
          />
          {initial?.has_file && !file && (
            <span className="res-current-file">
              {dropFile ? (
                <>
                  <s>{initial.file_name}</s> will be removed.{' '}
                  <button type="button" className="linkish" onClick={() => setDropFile(false)}>
                    Keep it
                  </button>
                </>
              ) : (
                <>
                  Current: {initial.file_name}{' '}
                  <button type="button" className="linkish" onClick={() => setDropFile(true)}>
                    Remove it
                  </button>
                </>
              )}
            </span>
          )}
        </label>
        <label className="span-all">
          Why is it worth reading?
          <textarea
            className="input"
            rows={4}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What you learned from it, which pages matter. Markdown works: **bold**, - lists, links."
            maxLength={8000}
          />
        </label>
      </div>
      <div className="order-form-foot">
        {problem && <span className="order-problem">{problem}</span>}
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}
