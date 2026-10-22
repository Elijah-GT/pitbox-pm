import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../api/client'
import type { LearnGroup, LearnIcon as IconName, LearnSection } from '../api/types'
import { LearnIcon } from './LearnIcon'
import { LearnPageView } from './LearnPageView'

const GROUPS: { key: LearnGroup; title: string; blurb: string; icon: IconName }[] = [
  {
    key: 'library',
    title: 'Resource library',
    blurb: 'Each topic has in-depth writeups first, followed by CAD references when available.',
    icon: 'book',
  },
  {
    key: 'cad',
    title: 'CAD best practices',
    blurb: 'How we model the car in Onshape, so anyone can pick up anyone else’s work.',
    icon: 'cube',
  },
]

const ICONS: IconName[] = ['gear', 'spring', 'wheel', 'weld', 'cube', 'book']

interface Props {
  /** The page on screen, from the URL; null for the index. */
  pageId: number | null
  /** Go to a page, or back to the index. Updates the URL so links can be shared. */
  onOpenPage: (id: number | null) => void
  /**
   * The only permission Learn uses. Everyone reads; admins change anything --
   * there is deliberately no member-level "edit" here, unlike the tree. These
   * pages are the team's guidance. See app/routers/learn.py.
   */
  isAdmin: boolean
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * The team's reference library, laid out like frcdesign.org: a card per topic
 * with its pages as chips, and each page a writeup followed by CAD references.
 *
 * Team-wide rather than per tree -- nothing here takes a project id.
 */
export function LearnView({ pageId, onOpenPage, isAdmin, onError, onToast }: Props) {
  const [library, setLibrary] = useState<LearnSection[] | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  // A page an admin just created: open it straight into the editor.
  const [freshPageId, setFreshPageId] = useState<number | null>(null)
  const scroller = useRef<HTMLElement>(null)

  const refresh = useCallback(() => {
    api
      .getLearn()
      .then((r) => setLibrary(r.sections))
      .catch(onError)
  }, [onError])

  useEffect(() => {
    let alive = true
    api
      .getLearn()
      .then((r) => {
        if (alive) setLibrary(r.sections)
      })
      .catch((err: unknown) => {
        if (alive) onError(err)
      })
    return () => {
      alive = false
    }
  }, [onError])

  // A new page should start at its top, not wherever the last one was scrolled.
  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [pageId])

  /** Navigate. Clears the "just created" flag, so only the first visit to a
   *  new page opens the editor -- not every visit after it. */
  function open(id: number | null) {
    setFreshPageId(null)
    onOpenPage(id)
  }

  async function addSection(group: LearnGroup) {
    const title = prompt(
      group === 'cad' ? 'Name for the new CAD guide:' : 'Name for the new topic (e.g. "Brakes"):',
    )
    if (!title?.trim()) return
    try {
      const made = await api.createLearnSection({
        title: title.trim(),
        group,
        icon: GROUPS.find((g) => g.key === group)?.icon ?? 'book',
      })
      setLibrary((prev) => [...(prev ?? []), made])
      setEditingId(made.id)
    } catch (err) {
      onError(err)
    }
  }

  async function addPage(section: LearnSection, title: string) {
    try {
      const made = await api.createLearnPage(section.id, title)
      refresh()
      setFreshPageId(made.id)
      onOpenPage(made.id)
    } catch (err) {
      onError(err)
    }
  }

  if (!library) return <p className="loading">Loading the library…</p>

  const section = pageId == null ? null : library.find((s) => s.pages.some((p) => p.id === pageId)) ?? null
  const editing = library.find((s) => s.id === editingId) ?? null

  return (
    <section className="learn" ref={scroller} aria-label="Learn">
      {pageId != null ? (
        <LearnPageView
          key={pageId}
          pageId={pageId}
          section={section}
          isAdmin={isAdmin}
          startEditing={freshPageId === pageId}
          onOpenPage={open}
          onAddPage={(title) => {
            if (section) void addPage(section, title)
          }}
          onLibrary={setLibrary}
          onChanged={refresh}
          onError={onError}
          onToast={onToast}
        />
      ) : (
        <div className="learn-index">
          <header className="learn-hero">
            <h2>Learn</h2>
            <p>The team’s own reference library — written by us, for whoever builds the car next.</p>
          </header>

          {GROUPS.map((group) => {
            const sections = library
              .filter((s) => s.group === group.key)
              .sort((a, b) => a.position - b.position || a.id - b.id)
            return (
              <div key={group.key} className="learn-group">
                <div className="learn-group-head">
                  <h3>{group.title}</h3>
                  <p>{group.blurb}</p>
                </div>
                <div className="learn-grid">
                  {sections.map((s) => (
                    <SectionCard
                      key={s.id}
                      section={s}
                      isAdmin={isAdmin}
                      onOpenPage={open}
                      onEdit={() => setEditingId(s.id)}
                      onAddPage={(title) => void addPage(s, title)}
                    />
                  ))}
                  {isAdmin && (
                    <button type="button" className="learn-card learn-card-add" onClick={() => void addSection(group.key)}>
                      + {group.key === 'cad' ? 'CAD guide' : 'Topic'}
                    </button>
                  )}
                  {sections.length === 0 && !isAdmin && (
                    <p className="learn-empty">Nothing here yet.</p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {editing && (
        <SectionEditor
          section={editing}
          isAdmin={isAdmin}
          onClose={() => setEditingId(null)}
          onSaved={(saved) =>
            setLibrary((prev) => (prev ?? []).map((s) => (s.id === saved.id ? saved : s)))
          }
          onReordered={setLibrary}
          onDeleted={() => {
            setEditingId(null)
            refresh()
            onToast('Section deleted')
          }}
          onError={onError}
        />
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ card */

function SectionCard({
  section, isAdmin, onOpenPage, onEdit, onAddPage,
}: {
  section: LearnSection
  isAdmin: boolean
  onOpenPage: (id: number) => void
  onEdit: () => void
  onAddPage: (title: string) => void
}) {
  const first = section.pages[0]
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')

  return (
    <article className="learn-card">
      <button
        type="button"
        className="learn-card-art"
        onClick={() => first && onOpenPage(first.id)}
        disabled={!first}
        aria-label={first ? `Open ${section.title}` : `${section.title} has no pages yet`}
      >
        {section.image_url ? (
          <img src={section.image_url} alt="" loading="lazy" />
        ) : (
          <LearnIcon name={section.icon} />
        )}
      </button>
      <div className="learn-card-body">
        <div className="learn-card-top">
          <h4>
            {first ? (
              <button type="button" className="learn-card-title" onClick={() => onOpenPage(first.id)}>
                {section.title}
              </button>
            ) : (
              section.title
            )}
          </h4>
          {isAdmin && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={onEdit}>
              Edit
            </button>
          )}
        </div>
        {section.summary && <p className="learn-card-summary">{section.summary}</p>}
        <div className="learn-chips">
          {section.pages.map((p) => (
            <button key={p.id} type="button" className="learn-chip" onClick={() => onOpenPage(p.id)}>
              {p.title}
            </button>
          ))}
          {section.pages.length === 0 && !isAdmin && <span className="learn-empty">No pages yet</span>}
          {isAdmin &&
            (adding ? (
              <form
                className="learn-chip-add"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!title.trim()) return
                  onAddPage(title.trim())
                  setTitle('')
                  setAdding(false)
                }}
              >
                <input
                  className="input"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Page title"
                  aria-label={`New page in ${section.title}`}
                  maxLength={160}
                  autoFocus
                />
                <button type="submit" className="btn btn-sm btn-primary">
                  Add
                </button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setAdding(false)}>
                  Cancel
                </button>
              </form>
            ) : (
              <button type="button" className="learn-chip learn-chip-new" onClick={() => setAdding(true)}>
                + Page
              </button>
            ))}
        </div>
      </div>
    </article>
  )
}

/* ---------------------------------------------------------------- editor */

function SectionEditor({
  section, isAdmin, onClose, onSaved, onReordered, onDeleted, onError,
}: {
  section: LearnSection
  isAdmin: boolean
  onClose: () => void
  onSaved: (s: LearnSection) => void
  onReordered: (all: LearnSection[]) => void
  onDeleted: () => void
  onError: (err: unknown) => void
}) {
  const [title, setTitle] = useState(section.title)
  const [summary, setSummary] = useState(section.summary ?? '')
  const [group, setGroup] = useState<LearnGroup>(section.group)
  const [icon, setIcon] = useState<IconName>(section.icon)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function run(work: () => Promise<void>) {
    setBusy(true)
    try {
      await work()
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    run(async () => {
      if (!title.trim()) throw new Error('The section needs a title.')
      onSaved(await api.updateLearnSection(section.id, { title: title.trim(), summary, group, icon }))
      onClose()
    })

  const remove = () => {
    // Typed, like deleting a tree: this takes every page and picture with it.
    const typed = prompt(
      `Delete "${section.title}" and its ${section.pages.length} page(s), with every picture in them?\n` +
        'There is no undo. Type the section name to confirm:',
    )
    if (typed === null) return
    if (typed.trim() !== section.title) {
      onError(new Error('The name did not match, so nothing was deleted.'))
      return
    }
    void run(async () => {
      await api.deleteLearnSection(section.id)
      onDeleted()
    })
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal learn-editor-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Edit ${section.title}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>Edit section</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="learn-form">
          <label>
            Title
            <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} />
          </label>
          <label>
            Summary
            <textarea
              className="input"
              rows={3}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              maxLength={600}
              placeholder="One or two sentences under the title on the card"
            />
          </label>
          <label>
            Shows under
            <select className="input" value={group} onChange={(e) => setGroup(e.target.value as LearnGroup)}>
              {GROUPS.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.title}
                </option>
              ))}
            </select>
          </label>

          <fieldset className="learn-icon-pick">
            <legend>Icon, when there is no picture</legend>
            {ICONS.map((name) => (
              <button
                key={name}
                type="button"
                className={icon === name ? 'active' : ''}
                aria-pressed={icon === name}
                aria-label={name}
                title={name}
                onClick={() => setIcon(name)}
              >
                <LearnIcon name={name} />
              </button>
            ))}
          </fieldset>

          <div className="learn-card-pic">
            <div className="learn-card-pic-preview">
              {section.image_url ? <img src={section.image_url} alt="" /> : <LearnIcon name={icon} />}
            </div>
            <div className="learn-card-pic-actions">
              <span className="learn-hint">A render or photo for the card. Saved as soon as you pick it.</span>
              <label className="btn btn-sm">
                {section.image_url ? 'Replace picture' : 'Upload picture'}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  hidden
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    e.target.value = ''
                    if (file) void run(async () => onSaved(await api.setLearnSectionImage(section.id, file)))
                  }}
                />
              </label>
              {section.image_url && (
                <button
                  type="button"
                  className="btn btn-sm btn-ghost"
                  onClick={() => void run(async () => onSaved(await api.clearLearnSectionImage(section.id)))}
                >
                  Use the icon instead
                </button>
              )}
            </div>
          </div>

          <div className="learn-move-row">
            <span className="learn-hint">Order on the page</span>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => void run(async () => onReordered((await api.moveLearnSection(section.id, 'up')).sections))}
            >
              ← Earlier
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy}
              onClick={() => void run(async () => onReordered((await api.moveLearnSection(section.id, 'down')).sections))}
            >
              Later →
            </button>
          </div>
        </div>

        <div className="learn-editor-foot">
          {isAdmin && (
            <button type="button" className="btn btn-danger" onClick={remove} disabled={busy}>
              Delete section
            </button>
          )}
          <span className="spacer" />
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={busy}>
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
