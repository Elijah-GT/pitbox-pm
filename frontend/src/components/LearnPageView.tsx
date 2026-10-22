import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
} from 'react'

import { ApiError, api } from '../api/client'
import type { LearnPage, LearnReference, LearnSection } from '../api/types'
import { safeHref } from '../lib/markdown'
import { LearnIcon } from './LearnIcon'
import { Markdown } from './Markdown'

const imageUrl = (id: number) => `/api/learn/images/${id}`

interface Props {
  pageId: number
  /** The section this page is in, from the library -- null until it loads. */
  section: LearnSection | null
  /** Admins change anything here; members read. See LearnView. */
  isAdmin: boolean
  /** Open straight into the editor: a page an admin has just created. */
  startEditing: boolean
  onOpenPage: (id: number | null) => void
  onAddPage: (title: string) => void
  onLibrary: (sections: LearnSection[]) => void
  /** Something the index shows has changed -- a title, a deleted page. */
  onChanged: () => void
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * One Learn page: a sidebar of the section's pages, then the writeup, its CAD
 * references, and previous/next -- the frcdesign.org reading layout.
 */
export function LearnPageView({
  pageId, section, isAdmin, startEditing,
  onOpenPage, onAddPage, onLibrary, onChanged, onError, onToast,
}: Props) {
  const [page, setPage] = useState<LearnPage | null>(null)
  const [missing, setMissing] = useState(false)
  const [editing, setEditing] = useState(startEditing && isAdmin)
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')

  useEffect(() => {
    let alive = true
    api
      .getLearnPage(pageId)
      .then((p) => {
        if (alive) setPage(p)
      })
      .catch((err: unknown) => {
        if (!alive) return
        if (err instanceof ApiError && err.status === 404) setMissing(true)
        else onError(err)
      })
    return () => {
      alive = false
    }
  }, [pageId, onError])

  const pages = section?.pages ?? []
  const index = pages.findIndex((p) => p.id === pageId)
  const prev = index > 0 ? pages[index - 1] : null
  const next = index >= 0 && index < pages.length - 1 ? pages[index + 1] : null

  async function move(direction: 'up' | 'down') {
    try {
      onLibrary((await api.moveLearnPage(pageId, direction)).sections)
    } catch (err) {
      onError(err)
    }
  }

  async function remove() {
    if (!page || !confirm(`Delete the page "${page.title}" and the pictures uploaded to it? There is no undo.`)) return
    try {
      await api.deleteLearnPage(page.id)
      onChanged()
      onToast('Page deleted')
      onOpenPage(next?.id ?? prev?.id ?? null)
    } catch (err) {
      onError(err)
    }
  }

  return (
    <div className="learn-page">
      <nav className="learn-side" aria-label={section?.title ?? 'Pages'}>
        <button type="button" className="learn-back" onClick={() => onOpenPage(null)}>
          ← All topics
        </button>
        {section && (
          <>
            <div className="learn-side-head">
              <LearnIcon name={section.icon} />
              <span>{section.title}</span>
            </div>
            <ol className="learn-side-list">
              {pages.map((p, i) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={p.id === pageId ? 'active' : ''}
                    aria-current={p.id === pageId ? 'page' : undefined}
                    onClick={() => onOpenPage(p.id)}
                  >
                    {p.title}
                  </button>
                  {isAdmin && p.id === pageId && pages.length > 1 && (
                    <span className="learn-move">
                      <button
                        type="button"
                        aria-label="Move this page earlier"
                        disabled={i === 0}
                        onClick={() => void move('up')}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        aria-label="Move this page later"
                        disabled={i === pages.length - 1}
                        onClick={() => void move('down')}
                      >
                        ↓
                      </button>
                    </span>
                  )}
                </li>
              ))}
            </ol>
            {isAdmin &&
              (adding ? (
                <form
                  className="learn-side-add"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (!newTitle.trim()) return
                    onAddPage(newTitle.trim())
                    setNewTitle('')
                    setAdding(false)
                  }}
                >
                  <input
                    className="input"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="Page title"
                    aria-label="New page title"
                    maxLength={160}
                    autoFocus
                  />
                  <button type="submit" className="btn btn-sm btn-primary">
                    Add
                  </button>
                </form>
              ) : (
                <button type="button" className="learn-side-new" onClick={() => setAdding(true)}>
                  + Page
                </button>
              ))}
          </>
        )}
      </nav>

      <article className="learn-article">
        {missing && (
          <div className="learn-missing">
            <h1>This page is gone</h1>
            <p>It may have been deleted, or the link is wrong.</p>
            <button type="button" className="btn" onClick={() => onOpenPage(null)}>
              Back to Learn
            </button>
          </div>
        )}
        {!missing && !page && <p className="loading">Loading…</p>}

        {page && editing && (
          <PageEditor
            page={page}
            onSaved={(saved) => {
              setPage(saved)
              setEditing(false)
              if (saved.title !== page.title) onChanged()
              onToast('Saved')
            }}
            onCancel={() => setEditing(false)}
            onError={onError}
            onToast={onToast}
          />
        )}

        {page && !editing && (
          <>
            <div className="learn-crumbs">
              <button type="button" onClick={() => onOpenPage(null)}>
                Learn
              </button>
              {section && (
                <>
                  <span aria-hidden="true">›</span>
                  <span>{section.title}</span>
                </>
              )}
            </div>
            <h1 className="learn-title">{page.title}</h1>
            <div className="learn-meta">
              <span>
                {page.updated_by_name
                  ? `Last edited by ${page.updated_by_name}${page.updated_at ? ` · ${formatWhen(page.updated_at)}` : ''}`
                  : 'Starter page'}
              </span>
              {isAdmin && (
                <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>
                  Edit page
                </button>
              )}
              {isAdmin && (
                <button type="button" className="btn btn-sm btn-ghost btn-danger" onClick={() => void remove()}>
                  Delete page
                </button>
              )}
            </div>

            {page.body.trim() ? (
              <Markdown source={page.body} />
            ) : (
              <p className="learn-empty">
                Nothing written here yet.{isAdmin && ' Use Edit page to start it.'}
              </p>
            )}

            {page.references.length > 0 && (
              <section className="learn-refs-section" aria-label="CAD references">
                <h2 className="learn-refs-head">CAD references</h2>
                <div className="learn-refs">
                  {page.references.map((r, i) => (
                    <ReferenceCard key={i} reference={r} />
                  ))}
                </div>
              </section>
            )}

            {(prev || next) && (
              <nav className="learn-prevnext" aria-label="More in this section">
                {prev ? (
                  <button type="button" onClick={() => onOpenPage(prev.id)}>
                    <span>← Previous</span>
                    {prev.title}
                  </button>
                ) : (
                  <span />
                )}
                {next && (
                  <button type="button" className="is-next" onClick={() => onOpenPage(next.id)}>
                    <span>Next →</span>
                    {next.title}
                  </button>
                )}
              </nav>
            )}
          </>
        )}
      </article>
    </div>
  )
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function ReferenceCard({ reference }: { reference: LearnReference }) {
  // Vetted again here even though the server only stores http(s): this is
  // about to become a real href.
  const link = safeHref(reference.url)
  const inner = (
    <>
      <div className="learn-ref-art">
        {reference.image_id ? (
          <img src={imageUrl(reference.image_id)} alt="" loading="lazy" />
        ) : (
          <LearnIcon name="cube" />
        )}
      </div>
      <div className="learn-ref-body">
        <span className="learn-ref-kicker">CAD reference</span>
        <span className="learn-ref-title">{reference.title}</span>
        {reference.description && <span className="learn-ref-desc">{reference.description}</span>}
      </div>
    </>
  )
  return link?.external ? (
    <a className="learn-ref" href={link.href} target="_blank" rel="noopener noreferrer">
      {inner}
    </a>
  ) : (
    <div className="learn-ref">{inner}</div>
  )
}

/* ---------------------------------------------------------------- editor */

interface Draft {
  title: string
  body: string
  references: LearnReference[]
  /** The page version the draft was written against. */
  version: number
  at: number
}

// Unsaved work is kept in this browser, so switching to the Shop tab, a
// reload or a crash does not throw away an hour of writing. Every access is
// guarded: private windows and full storage throw, and the editor has to keep
// working without the safety net.
function readDraft(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const draft = JSON.parse(raw) as Draft
    return typeof draft?.body === 'string' && typeof draft.title === 'string' ? draft : null
  } catch {
    return null
  }
}

function writeDraft(key: string, draft: Draft): void {
  try {
    localStorage.setItem(key, JSON.stringify(draft))
  } catch {
    // No room or no storage: carry on without the backup.
  }
}

function dropDraft(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}

const sameRefs = (a: LearnReference[], b: LearnReference[]) => JSON.stringify(a) === JSON.stringify(b)

/** "cad.onshape.com/documents/x" -> "https://cad.onshape.com/documents/x". */
function withScheme(raw: string): string {
  const url = raw.trim()
  if (!url || /^[a-z][a-z0-9+.-]*:/i.test(url)) return url
  return `https://${url}`
}

const PICTURE_TYPES = 'image/png,image/jpeg,image/gif,image/webp'

function PageEditor({
  page, onSaved, onCancel, onError, onToast,
}: {
  page: LearnPage
  onSaved: (saved: LearnPage) => void
  onCancel: () => void
  onError: (err: unknown) => void
  onToast: (message: string) => void
}) {
  const draftKey = `carhub.learn.draft.${page.id}`
  const [title, setTitle] = useState(page.title)
  const [body, setBody] = useState(page.body)
  const [refs, setRefs] = useState<LearnReference[]>(page.references)
  const [tab, setTab] = useState<'write' | 'preview'>('write')
  const [busy, setBusy] = useState(false)
  const [uploads, setUploads] = useState(0)
  const [problem, setProblem] = useState<string | null>(null)
  const [conflict, setConflict] = useState<string | null>(null)
  const [showHelp, setShowHelp] = useState(false)
  // A draft left over from an earlier visit, offered once and never silently
  // applied -- it might be stale, or someone may have saved since.
  const [stored, setStored] = useState<Draft | null>(() => {
    const d = readDraft(draftKey)
    return d && (d.title !== page.title || d.body !== page.body || !sameRefs(d.references, page.references))
      ? d
      : null
  })
  const text = useRef<HTMLTextAreaElement>(null)

  const dirty = title !== page.title || body !== page.body || !sameRefs(refs, page.references)

  useEffect(() => {
    // Hold off while an old draft is on offer, so typing does not overwrite
    // it before the writer has decided whether they want it back.
    if (!dirty || stored) return
    const timer = setTimeout(
      () => writeDraft(draftKey, { title, body, references: refs, version: page.version, at: Date.now() }),
      400,
    )
    return () => clearTimeout(timer)
  }, [dirty, stored, title, body, refs, draftKey, page.version])

  /* --- text helpers --- */

  function focusAt(start: number, end = start) {
    requestAnimationFrame(() => {
      text.current?.focus()
      text.current?.setSelectionRange(start, end)
    })
  }

  /** Wrap the selection, or a placeholder, in Markdown -- then select it. */
  function surround(before: string, after: string, placeholder: string) {
    const ta = text.current
    if (!ta) return
    const { selectionStart: s, selectionEnd: e, value } = ta
    const picked = value.slice(s, e) || placeholder
    setBody(value.slice(0, s) + before + picked + after + value.slice(e))
    focusAt(s + before.length, s + before.length + picked.length)
  }

  /** Put a prefix ("## ", "- ", "> ") on every line the selection touches. */
  function prefixLines(prefix: string) {
    const ta = text.current
    if (!ta) return
    const { selectionStart: s, selectionEnd: e, value } = ta
    const start = value.lastIndexOf('\n', s - 1) + 1
    const lines = value.slice(start, e).split('\n').map((l) => prefix + l).join('\n')
    setBody(value.slice(0, start) + lines + value.slice(e))
    focusAt(start + lines.length)
  }

  /** Insert on its own line, so a picture renders as a figure. */
  function insertBlock(snippet: string) {
    const ta = text.current
    setBody((current) => {
      const s = ta ? Math.min(ta.selectionStart, current.length) : current.length
      const e = ta ? Math.min(ta.selectionEnd, current.length) : current.length
      const before = current.slice(0, s)
      const after = current.slice(e)
      const lead = before === '' || before.endsWith('\n\n') ? '' : before.endsWith('\n') ? '\n' : '\n\n'
      const trail = after.startsWith('\n\n') ? '' : after.startsWith('\n') ? '\n' : '\n\n'
      return before + lead + snippet + trail + after
    })
    requestAnimationFrame(() => {
      const at = text.current?.value.indexOf(snippet) ?? -1
      if (at >= 0) focusAt(at + snippet.length)
    })
  }

  /* --- pictures --- */

  async function uploadPicture(file: File): Promise<number | null> {
    if (!file.type.startsWith('image/')) {
      onError(new Error(`"${file.name}" is not a picture. PNG, JPEG, GIF or WebP.`))
      return null
    }
    setUploads((n) => n + 1)
    try {
      return (await api.uploadLearnImage(page.section_id, file, page.id)).id
    } catch (err) {
      onError(err)
      return null
    } finally {
      setUploads((n) => n - 1)
    }
  }

  async function addPictures(files: File[]) {
    for (const file of files) {
      // A placeholder goes in at once, so the writer sees where it will land
      // and can keep typing while it uploads.
      const token = `![Uploading ${file.name.replace(/[[\]]/g, '')}…]()`
      insertBlock(token)
      const id = await uploadPicture(file)
      // Pasted screenshots are all called "image.png" -- not a caption.
      const caption = /^image\.\w+$/i.test(file.name) ? '' : file.name.replace(/\.[^.]+$/, '').replace(/[[\]]/g, '')
      setBody((current) => current.replace(token, id != null ? `![${caption}](${imageUrl(id)})` : ''))
    }
  }

  function onPaste(e: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith('image/'))
    if (files.length) {
      // A screenshot copied out of Onshape goes straight in as a picture.
      e.preventDefault()
      void addPictures(files)
    }
  }

  function onDrop(e: DragEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith('image/'))
    if (files.length) {
      e.preventDefault()
      void addPictures(files)
    }
  }

  /* --- references --- */

  const updateRef = (i: number, patch: Partial<LearnReference>) =>
    setRefs((all) => all.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  function moveRef(i: number, by: -1 | 1) {
    setRefs((all) => {
      const j = i + by
      if (j < 0 || j >= all.length) return all
      const next = [...all]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  /* --- save --- */

  async function save() {
    const cleaned = refs
      .map((r) => ({
        ...r,
        title: r.title.trim(),
        url: withScheme(r.url),
        description: r.description?.trim() || null,
      }))
      .filter((r) => r.title || r.url || r.image_id)
    if (!title.trim()) return setProblem('The page needs a title.')
    if (cleaned.some((r) => !r.title || !r.url)) {
      return setProblem('Each CAD reference needs a title and a link.')
    }
    if (uploads > 0) return setProblem('Wait for the pictures to finish uploading.')
    setProblem(null)

    setBusy(true)
    try {
      const saved = await api.updateLearnPage(page.id, {
        title: title.trim(),
        body,
        references: cleaned,
        base_version: page.version,
      })
      dropDraft(draftKey)
      onSaved(saved)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setConflict(err.message)
      else onError(err)
    } finally {
      setBusy(false)
    }
  }

  function cancel() {
    if (dirty && !confirm('Discard your changes to this page?')) return
    dropDraft(draftKey)
    onCancel()
  }

  return (
    <div className="learn-edit">
      {stored && (
        <div className="learn-banner">
          <span>
            You have unsaved changes to this page from{' '}
            {new Date(stored.at).toLocaleString(undefined, {
              month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
            })}
            .
            {stored.version !== page.version &&
              ' Someone has saved the page since then — restoring your draft and saving would replace their changes, so compare first.'}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => {
              setTitle(stored.title)
              setBody(stored.body)
              setRefs(stored.references ?? [])
              setStored(null)
            }}
          >
            Restore
          </button>
          <button
            type="button"
            className="btn btn-sm btn-ghost"
            onClick={() => {
              dropDraft(draftKey)
              setStored(null)
            }}
          >
            Discard
          </button>
        </div>
      )}

      {conflict && (
        <div className="learn-banner is-bad" role="alert">
          <span>{conflict}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() =>
              void navigator.clipboard
                .writeText(body)
                .then(() => onToast('Your text is on the clipboard'))
                .catch(() => onError(new Error('Could not copy — select the text and copy it by hand.')))
            }
          >
            Copy my text
          </button>
        </div>
      )}

      <label className="learn-edit-title">
        <span className="sr-only">Page title</span>
        <input
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={160}
          aria-label="Page title"
        />
      </label>

      <div className="learn-toolbar" role="toolbar" aria-label="Formatting">
        <div className="segmented" role="group" aria-label="Editor view">
          <button type="button" className={tab === 'write' ? 'active' : ''} aria-pressed={tab === 'write'} onClick={() => setTab('write')}>
            Write
          </button>
          <button type="button" className={tab === 'preview' ? 'active' : ''} aria-pressed={tab === 'preview'} onClick={() => setTab('preview')}>
            Preview
          </button>
        </div>
        {tab === 'write' && (
          <>
            <button type="button" className="btn btn-sm" title="Bold" onClick={() => surround('**', '**', 'bold text')}>
              <b>B</b>
            </button>
            <button type="button" className="btn btn-sm" title="Italic" onClick={() => surround('*', '*', 'italic text')}>
              <i>I</i>
            </button>
            <button type="button" className="btn btn-sm" title="Heading" onClick={() => prefixLines('## ')}>
              H
            </button>
            <button type="button" className="btn btn-sm" title="Bulleted list" onClick={() => prefixLines('- ')}>
              • List
            </button>
            <button type="button" className="btn btn-sm" title="Numbered list" onClick={() => prefixLines('1. ')}>
              1. List
            </button>
            <button type="button" className="btn btn-sm" title="Link" onClick={() => surround('[', '](https://)', 'link text')}>
              Link
            </button>
            <button type="button" className="btn btn-sm" title="Note callout" onClick={() => prefixLines('> ')}>
              Note
            </button>
            <label className="btn btn-sm" title="Insert a picture — or paste or drop one into the text">
              Picture
              <input
                type="file"
                accept={PICTURE_TYPES}
                multiple
                hidden
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? [])
                  e.target.value = ''
                  void addPictures(files)
                }}
              />
            </label>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              aria-expanded={showHelp}
              onClick={() => setShowHelp((v) => !v)}
            >
              Formatting help
            </button>
          </>
        )}
        {uploads > 0 && <span className="learn-hint">Uploading {uploads} picture{uploads === 1 ? '' : 's'}…</span>}
      </div>

      {showHelp && tab === 'write' && (
        <div className="learn-help">
          <code>## Heading</code> <code>**bold**</code> <code>*italic*</code> <code>- bullet</code>{' '}
          <code>1. step</code> <code>&gt; note</code> <code>[text](https://…)</code> <code>`code`</code>{' '}
          <code>| a | b |</code> tables. Paste or drop a screenshot to add a picture.
        </div>
      )}

      {tab === 'write' ? (
        <textarea
          ref={text}
          className="input learn-textarea"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onPaste={onPaste}
          onDrop={onDrop}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes('Files')) e.preventDefault()
          }}
          placeholder="Write the page here. Paste a screenshot to add a picture."
          aria-label="Page text"
          spellCheck
        />
      ) : (
        <div className="learn-preview">
          <h1 className="learn-title">{title || 'Untitled'}</h1>
          {body.trim() ? <Markdown source={body} /> : <p className="learn-empty">Nothing written yet.</p>}
        </div>
      )}

      <fieldset className="learn-refs-edit">
        <legend>CAD references</legend>
        <p className="learn-hint">
          Cards under the writeup, linking to models in Onshape. Each needs a title and a link.
        </p>
        {refs.map((r, i) => (
          <div key={i} className="learn-ref-row">
            <div className="learn-ref-pic">
              {r.image_id ? <img src={imageUrl(r.image_id)} alt="" /> : <LearnIcon name="cube" />}
            </div>
            <div className="learn-ref-fields">
              <input
                className="input"
                value={r.title}
                onChange={(e) => updateRef(i, { title: e.target.value })}
                placeholder="Title, e.g. 2026 front upright"
                aria-label="Reference title"
                maxLength={120}
              />
              <input
                className="input"
                value={r.url}
                onChange={(e) => updateRef(i, { url: e.target.value })}
                placeholder="Onshape link"
                aria-label="Reference link"
                inputMode="url"
              />
              <input
                className="input"
                value={r.description ?? ''}
                onChange={(e) => updateRef(i, { description: e.target.value })}
                placeholder="One line about it (optional)"
                aria-label="Reference description"
                maxLength={300}
              />
            </div>
            <div className="learn-ref-tools">
              <label className="btn btn-sm">
                {r.image_id ? 'New picture' : 'Picture'}
                <input
                  type="file"
                  accept={PICTURE_TYPES}
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (file) void uploadPicture(file).then((id) => id != null && updateRef(i, { image_id: id }))
                  }}
                />
              </label>
              {r.image_id && (
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => updateRef(i, { image_id: null })}>
                  No picture
                </button>
              )}
              <button type="button" className="btn btn-sm btn-ghost" aria-label="Move up" disabled={i === 0} onClick={() => moveRef(i, -1)}>
                ↑
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                aria-label="Move down"
                disabled={i === refs.length - 1}
                onClick={() => moveRef(i, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost btn-danger"
                aria-label="Remove reference"
                onClick={() => setRefs((all) => all.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          className="btn btn-sm"
          disabled={refs.length >= 24}
          onClick={() => setRefs((all) => [...all, { title: '', url: '', description: null, image_id: null }])}
        >
          + Add CAD reference
        </button>
      </fieldset>

      <div className="learn-edit-foot">
        {problem && <span className="order-problem">{problem}</span>}
        <span className="spacer" />
        <button type="button" className="btn btn-ghost" onClick={cancel} disabled={busy}>
          Cancel
        </button>
        <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={busy}>
          {busy ? 'Saving…' : 'Save page'}
        </button>
      </div>
    </div>
  )
}
