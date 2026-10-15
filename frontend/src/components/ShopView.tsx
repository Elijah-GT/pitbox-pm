import { useEffect, useMemo, useRef, useState } from 'react'

import { api } from '../api/client'
import type { Member, MfgPart, MfgStatus } from '../api/types'
import { humanSize } from '../lib/format'

const STATUS_LABELS: Record<MfgStatus, string> = {
  todo: 'To make',
  in_progress: 'In progress',
  done: 'Done',
}
const STATUS_ORDER = Object.keys(STATUS_LABELS) as MfgStatus[]

/** Types the browser can draw. Anything else gets a tile and a download. */
const VIEWABLE = new Set([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'application/pdf',
])

const isImage = (type: string | null) => Boolean(type?.startsWith('image/'))

interface Props {
  projectId: number
  projectName: string
  /** This car's own subsystem names, offered as suggestions. */
  subsystems: string[]
  members: Member[]
  canEdit: boolean
  isAdmin: boolean
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * The cut list: everything the shop has to make, as cards.
 *
 * Cards rather than a tree, and rather than a table. A tree would be wrong --
 * this is not the car's structure, it is a pile of work. A table would be
 * wrong too, because the drawing is the most useful thing about each part and
 * a table cell is a terrible place to put one. A card gives the drawing room
 * to be looked at, which is the whole reason it is in here.
 *
 * Grouped by subsystem, because that is how the work gets handed out.
 */
export function ShopView({
  projectId,
  projectName,
  subsystems,
  members,
  canEdit,
  isAdmin,
  onError,
  onToast,
}: Props) {
  // Stored WITH the project it came from and compared during render, so
  // switching trees shows the loading state without an effect having to reset
  // it first -- and the last project's parts never flash under the new name.
  const [loaded, setLoaded] = useState<{ projectId: number; rows: MfgPart[] } | null>(null)
  const parts = loaded && loaded.projectId === projectId ? loaded.rows : null

  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSubsystem, setNewSubsystem] = useState('')
  const [viewingId, setViewingId] = useState<number | null>(null)
  // Bumped after every upload so the <img>/<iframe> refetches: a part's
  // drawing URL never changes, so without this the browser keeps showing the
  // revision it already cached.
  const [drawingRev, setDrawingRev] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .listMfgParts(projectId)
      .then((rows) => {
        if (!cancelled) setLoaded({ projectId, rows })
      })
      .catch(onError)
    return () => {
      cancelled = true
    }
  }, [projectId, onError])

  const setRows = (fn: (rows: MfgPart[]) => MfgPart[]) =>
    setLoaded((cur) => (cur && cur.projectId === projectId ? { ...cur, rows: fn(cur.rows) } : cur))

  const replace = (updated: MfgPart) =>
    setRows((rows) => rows.map((p) => (p.id === updated.id ? updated : p)))

  const patch = async (id: number, body: Parameters<typeof api.updateMfgPart>[1]) => {
    try {
      replace(await api.updateMfgPart(id, body))
    } catch (err) {
      onError(err)
    }
  }

  const add = async () => {
    const name = newName.trim()
    if (!name) return
    try {
      const made = await api.createMfgPart({
        project_id: projectId,
        name,
        subsystem: newSubsystem.trim() || null,
      })
      setRows((rows) => [...rows, made])
      setNewName('')
      // Subsystem deliberately kept: you add six rollcage tubes in a row.
      setAdding(false)
      onToast(`Added "${made.name}"`)
    } catch (err) {
      onError(err)
    }
  }

  const remove = async (part: MfgPart) => {
    if (!confirm(`Delete "${part.name}" from the cut list?`)) return
    try {
      await api.deleteMfgPart(part.id)
      setRows((rows) => rows.filter((p) => p.id !== part.id))
      if (viewingId === part.id) setViewingId(null)
      onToast(`Deleted "${part.name}"`)
    } catch (err) {
      onError(err)
    }
  }

  const upload = async (part: MfgPart, file: File | null | undefined) => {
    if (!file) return
    onToast(`Uploading ${file.name}…`)
    try {
      replace(await api.uploadDrawing(part.id, file))
      setDrawingRev((n) => n + 1)
      onToast(`Drawing added to "${part.name}"`)
    } catch (err) {
      onError(err)
    }
  }

  const removeDrawing = async (part: MfgPart) => {
    if (
      !confirm(`Remove the drawing from "${part.name}"? There is no older version to fall back on.`)
    ) {
      return
    }
    try {
      replace(await api.clearDrawing(part.id))
      setDrawingRev((n) => n + 1)
    } catch (err) {
      onError(err)
    }
  }

  const memberName = useMemo(() => {
    const byId = new Map(members.map((m) => [m.id, m.name]))
    return (id: number | null) => (id == null ? null : (byId.get(id) ?? null))
  }, [members])

  // Server order is already subsystem-then-name; this only cuts it into groups.
  const groups = useMemo(() => {
    const out: { subsystem: string | null; rows: MfgPart[] }[] = []
    for (const part of parts ?? []) {
      const last = out[out.length - 1]
      if (last && last.subsystem === part.subsystem) last.rows.push(part)
      else out.push({ subsystem: part.subsystem, rows: [part] })
    }
    return out
  }, [parts])

  if (parts === null) return <p className="loading">Loading the cut list…</p>

  const viewing = parts.find((p) => p.id === viewingId) ?? null
  const doneCount = parts.filter((p) => p.status === 'done').length
  const noDrawing = parts.filter((p) => !p.has_drawing).length

  return (
    <section className="shop" aria-label="Manufacturing list">
      <header className="shop-head">
        <h2>
          Cut list <span className="shop-project">{projectName}</span>
        </h2>
        <div className="shop-stats">
          <span>{`${doneCount} of ${parts.length} made`}</span>
          {noDrawing > 0 && (
            <span className="shop-stat-warn">{`${noDrawing} without a drawing`}</span>
          )}
        </div>
        {isAdmin && !adding && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>
            + Part
          </button>
        )}
      </header>

      {adding && (
        <div className="shop-add">
          <input
            className="input"
            autoFocus
            placeholder="Part name — exactly as it is in Onshape"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void add()
              if (e.key === 'Escape') setAdding(false)
            }}
          />
          {/* A datalist, not a select: these are this car's own subsystem names,
              but a jig belongs to none of them and should not need a code
              change to be filed somewhere. */}
          <input
            className="input compact"
            list="shop-subsystems"
            placeholder="Subsystem"
            aria-label="Subsystem"
            value={newSubsystem}
            onChange={(e) => setNewSubsystem(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void add()
              if (e.key === 'Escape') setAdding(false)
            }}
          />
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!newName.trim()}
            onClick={() => void add()}
          >
            Add
          </button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(false)}>
            Cancel
          </button>
        </div>
      )}

      <datalist id="shop-subsystems">
        {subsystems.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>

      {parts.length === 0 ? (
        <p className="loading">
          {isAdmin
            ? 'Nothing on the cut list yet. Click “+ Part” to add the first one.'
            : 'Nothing on the cut list yet. A team lead can add parts.'}
        </p>
      ) : (
        groups.map((group) => (
          <div className="shop-group" key={group.subsystem ?? '__none__'}>
            <h3 className="shop-group-head">
              {group.subsystem ?? 'No subsystem'}
              <span className="count">{group.rows.length}</span>
            </h3>

            <div className="shop-cards">
              {group.rows.map((part) => (
                <PartCard
                  key={part.id}
                  part={part}
                  rev={drawingRev}
                  members={members}
                  assigneeName={memberName(part.assignee_id)}
                  canEdit={canEdit}
                  isAdmin={isAdmin}
                  onPatch={patch}
                  onUpload={upload}
                  onRemoveDrawing={removeDrawing}
                  onDelete={remove}
                  onOpen={() => setViewingId(part.id)}
                />
              ))}
            </div>
          </div>
        ))
      )}

      {viewing && viewing.has_drawing && (
        <DrawingViewer part={viewing} rev={drawingRev} onClose={() => setViewingId(null)} />
      )}
    </section>
  )
}

/* ------------------------------------------------------------------- card */

function PartCard({
  part,
  rev,
  members,
  assigneeName,
  canEdit,
  isAdmin,
  onPatch,
  onUpload,
  onRemoveDrawing,
  onDelete,
  onOpen,
}: {
  part: MfgPart
  rev: number
  members: Member[]
  assigneeName: string | null
  canEdit: boolean
  isAdmin: boolean
  onPatch: (id: number, body: Parameters<typeof api.updateMfgPart>[1]) => void
  onUpload: (part: MfgPart, file: File | null | undefined) => void
  onRemoveDrawing: (part: MfgPart) => void
  onDelete: (part: MfgPart) => void
  onOpen: () => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const viewable = part.has_drawing && VIEWABLE.has(part.drawing_content_type ?? '')

  return (
    <article className={`shop-card status-${part.status}`}>
      {/* --- the drawing ------------------------------------------------- */}
      {part.has_drawing ? (
        <div className="shop-drawing">
          {isImage(part.drawing_content_type) ? (
            // A real thumbnail: cheap, and you can tell the parts apart.
            <button type="button" className="shop-thumb" onClick={onOpen} title="View full size">
              <img src={`${api.drawingUrl(part.id)}#${rev}`} alt={`Drawing for ${part.name}`} />
            </button>
          ) : (
            // A tile rather than an embedded viewer. Thirty cards would mean
            // thirty PDF viewers booting at once; the full view is one click
            // away and only ever loads the one you asked for.
            <button
              type="button"
              className={`shop-thumb shop-thumb-file${viewable ? '' : ' not-viewable'}`}
              onClick={viewable ? onOpen : undefined}
              title={viewable ? 'View full size' : 'This file type can only be downloaded'}
            >
              <span className="shop-filetype">
                {(part.drawing_filename?.split('.').pop() ?? 'file').toUpperCase()}
              </span>
              <span className="shop-filename">{part.drawing_filename}</span>
              {part.drawing_size_bytes != null && (
                <span className="shop-filesize">{humanSize(part.drawing_size_bytes)}</span>
              )}
            </button>
          )}

          <div className="shop-drawing-actions">
            {viewable && (
              <button type="button" className="btn btn-sm btn-ghost" onClick={onOpen}>
                View
              </button>
            )}
            {/* A real link, not a fetch: the server's Content-Disposition is
                what makes this save rather than navigate. */}
            <a className="btn btn-sm btn-ghost" href={api.drawingUrl(part.id, true)}>
              Download
            </a>
            {canEdit && (
              <>
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => fileRef.current?.click()}
                >
                  Replace
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  title="Remove this drawing"
                  aria-label={`Remove the drawing from ${part.name}`}
                  onClick={() => onRemoveDrawing(part)}
                >
                  ×
                </button>
              </>
            )}
          </div>
        </div>
      ) : (
        canEdit && (
          <button
            type="button"
            className={`shop-dropzone${over ? ' over' : ''}`}
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault()
              setOver(true)
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setOver(false)
              onUpload(part, e.dataTransfer.files?.[0])
            }}
          >
            Drop the Onshape drawing here, or click to browse
          </button>
        )
      )}

      {!part.has_drawing && !canEdit && <p className="shop-nodrawing">No drawing yet.</p>}

      <input
        ref={fileRef}
        type="file"
        hidden
        onChange={(e) => {
          onUpload(part, e.target.files?.[0])
          e.target.value = ''
        }}
      />

      {/* --- the part ---------------------------------------------------- */}
      <input
        className="input shop-name"
        defaultValue={part.name}
        disabled={!canEdit}
        aria-label="Part name"
        title="Matches the part's name in Onshape"
        onBlur={(e) => {
          const v = e.target.value.trim()
          if (v && v !== part.name) onPatch(part.id, { name: v })
          else e.target.value = part.name
        }}
      />

      <div className="shop-row">
        <select
          className="input compact"
          defaultValue={part.status}
          disabled={!canEdit}
          aria-label="Status"
          onChange={(e) => onPatch(part.id, { status: e.target.value as MfgStatus })}
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <select
          className="input compact"
          defaultValue={part.assignee_id == null ? '' : String(part.assignee_id)}
          disabled={!canEdit}
          aria-label="Who is making it"
          title={assigneeName ?? 'Nobody yet'}
          onChange={(e) =>
            onPatch(part.id, {
              assignee_id: e.target.value === '' ? null : Number(e.target.value),
            })
          }
        >
          <option value="">Nobody</option>
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      <input
        className="input compact"
        list="shop-subsystems"
        defaultValue={part.subsystem ?? ''}
        disabled={!canEdit}
        aria-label="Subsystem"
        placeholder="Subsystem"
        onBlur={(e) => {
          const v = e.target.value.trim()
          if (v !== (part.subsystem ?? '')) onPatch(part.id, { subsystem: v || null })
        }}
      />

      <textarea
        className="shop-notes"
        defaultValue={part.notes ?? ''}
        disabled={!canEdit}
        aria-label="Notes"
        placeholder="Material, wall thickness, how many, how to cut it…"
        onBlur={(e) => {
          const v = e.target.value.trim()
          if (v !== (part.notes ?? '')) onPatch(part.id, { notes: v || null })
        }}
      />

      <LinkList part={part} canEdit={canEdit} onPatch={onPatch} />

      {isAdmin && (
        <button
          type="button"
          className="btn btn-sm btn-danger shop-delete"
          onClick={() => onDelete(part)}
        >
          Delete part
        </button>
      )}
    </article>
  )
}

/* ------------------------------------------------------------------ links */

/** Strip the scheme and any trailing slash, so a long Onshape URL still reads
 *  as something in the narrow space a card has. */
function shortUrl(url: string): string {
  return url.replace(/^https?:\/\//i, '').replace(/\/$/, '')
}

function LinkList({
  part,
  canEdit,
  onPatch,
}: {
  part: MfgPart
  canEdit: boolean
  onPatch: (id: number, body: Parameters<typeof api.updateMfgPart>[1]) => void
}) {
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const links = part.links ?? []

  const save = (next: typeof links) => onPatch(part.id, { links: next })

  const add = () => {
    let u = url.trim()
    if (!u) return
    // Typing "cad.onshape.com/..." is the normal thing to do, and the server
    // rejects anything without a scheme -- so assume https rather than
    // bouncing it back with a validation error.
    if (!/^https?:\/\//i.test(u)) u = `https://${u}`
    save([...links, { label: label.trim() || null, url: u }])
    setLabel('')
    setUrl('')
    setAdding(false)
  }

  return (
    <div className="shop-links">
      {links.map((link, i) => (
        <span className="shop-link" key={`${link.url}-${i}`}>
          {/* noreferrer as well as noopener: these URLs come from whoever
              edited the part, and the referrer would leak the CarHub hostname
              to wherever they point. */}
          <a href={link.url} target="_blank" rel="noopener noreferrer" title={link.url}>
            {link.label || shortUrl(link.url)}
          </a>
          {canEdit && (
            <button
              type="button"
              title="Remove this link"
              aria-label={`Remove link ${link.label || link.url}`}
              onClick={() => save(links.filter((_, j) => j !== i))}
            >
              ×
            </button>
          )}
        </span>
      ))}

      {canEdit &&
        (adding ? (
          <div className="shop-link-add">
            <input
              className="input compact"
              autoFocus
              placeholder="Label (optional)"
              aria-label="Link label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') add()
                if (e.key === 'Escape') setAdding(false)
              }}
            />
            <input
              className="input compact"
              placeholder="Paste the Onshape link"
              aria-label="Link URL"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') add()
                if (e.key === 'Escape') setAdding(false)
              }}
            />
            <button type="button" className="btn btn-sm btn-primary" disabled={!url.trim()} onClick={add}>
              Add
            </button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" className="shop-link-new" onClick={() => setAdding(true)}>
            + Link
          </button>
        ))}
    </div>
  )
}

/* ----------------------------------------------------------------- viewer */

function DrawingViewer({
  part,
  rev,
  onClose,
}: {
  part: MfgPart
  rev: number
  onClose: () => void
}) {
  const [full, setFull] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // In native full screen the browser spends Escape on leaving it. Closing
      // the dialog as well would drop you back to the cut list in one keypress,
      // when all you wanted was the window back.
      if (document.fullscreenElement) return
      onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Full screen can end without us -- Escape, F11, another tab taking it -- so
  // the button's label follows the browser rather than the last click.
  useEffect(() => {
    const sync = () => {
      if (!document.fullscreenElement) setFull(false)
    }
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  /**
   * The `is-full` class is what actually fills the window; `requestFullscreen`
   * is a bonus on top, worth having on a shop TV where the browser chrome is
   * wasted space. Order matters: the class goes on either way, so a browser
   * that refuses the API still gives you the big drawing.
   */
  const toggleFull = () => {
    if (full) {
      setFull(false)
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
      return
    }
    setFull(true)
    void panelRef.current?.requestFullscreen?.().catch(() => {})
  }

  const url = `${api.drawingUrl(part.id)}#${rev}`

  return (
    <div
      className={`modal-backdrop${full ? ' is-full' : ''}`}
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panelRef}
        className={`modal shop-viewer${full ? ' is-full' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={`Drawing for ${part.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>{part.name}</h2>
          <div className="shop-viewer-actions">
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              onClick={toggleFull}
              aria-pressed={full}
            >
              {full ? 'Exit full screen' : 'Full screen'}
            </button>
            <a className="btn btn-sm btn-ghost" href={api.drawingUrl(part.id, true)}>
              Download
            </a>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {isImage(part.drawing_content_type) ? (
          <img className="shop-viewer-img" src={url} alt={`Drawing for ${part.name}`} />
        ) : (
          // No `sandbox` attribute here, deliberately, and no CSP sandbox on
          // the response either (see serve_drawing in app/routers/mfg.py).
          // Chrome's PDF viewer is itself JavaScript, so a sandboxed PDF is
          // refused outright -- "This page has been blocked by Chrome" -- and
          // sandbox="allow-scripts" fares no better. You can sandbox a PDF or
          // display it, not both. The real fix, if a hostile upload ever
          // becomes a worry, is serving drawings from a separate hostname so
          // they are cross-origin by construction.
          <iframe className="shop-viewer-frame" src={url} title={`Drawing for ${part.name}`} />
        )}

        <p className="shop-viewer-foot">{part.drawing_filename}</p>
      </div>
    </div>
  )
}
