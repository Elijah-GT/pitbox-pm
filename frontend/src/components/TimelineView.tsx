import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type { GoalKind, GoalPriority, Member, Milestone, TreeNode } from '../api/types'
import {
  dueLabel,
  formatDay,
  KIND_LABELS,
  KIND_ORDER,
  KIND_TAGS,
  placeAll,
  positionOf,
  PRIORITY_LABELS,
  PRIORITY_ORDER,
  PRIORITY_TAGS,
  spanOf,
  today,
} from '../lib/timeline'

interface Props {
  projectId: number
  projectName: string
  /** Parts, so a goal can point at the thing it is about. */
  nodes: TreeNode[]
  members: Member[]
  canEdit: boolean
  isAdmin: boolean
  /** Jump to a linked part: switches back to the breakdown and selects it. */
  onOpenNode: (id: number) => void
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * The project timeline: dated goals on a horizontal axis, labels alternating
 * above and below, the way the team already draws it on the whiteboard.
 *
 * Two halves. The axis is for seeing shape — what is late, what is about to
 * be, how much is crammed into February. The list under it is for doing the
 * work, because editing a date is much easier in a row than on a flag.
 */
export function TimelineView({
  projectId,
  projectName,
  nodes,
  members,
  canEdit,
  isAdmin,
  onOpenNode,
  onError,
  onToast,
}: Props) {
  // Stored WITH the project they came from, and compared during render, so
  // switching trees shows the loading state immediately without an effect
  // having to reset it first. Keeps the old project's goals from flashing up
  // under the new project's name.
  const [loaded, setLoaded] = useState<{ projectId: number; rows: Milestone[] } | null>(null)
  const goals = loaded && loaded.projectId === projectId ? loaded.rows : null
  const [adding, setAdding] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDate, setNewDate] = useState('')
  // Settable at creation, because you know a submission is an SAE deadline at
  // the moment you write it down, not later.
  const [newPriority, setNewPriority] = useState<GoalPriority>('normal')
  const [newKind, setNewKind] = useState<GoalKind>('other')

  const now = useMemo(() => today(), [])

  useEffect(() => {
    let cancelled = false
    api
      .listMilestones(projectId)
      .then((rows) => {
        if (!cancelled) setLoaded({ projectId, rows })
      })
      .catch(onError)
    return () => {
      cancelled = true
    }
  }, [projectId, onError])

  /** Edit the loaded rows, but only if they still belong to this project. */
  const setRows = (fn: (rows: Milestone[]) => Milestone[]) =>
    setLoaded((cur) => (cur && cur.projectId === projectId ? { ...cur, rows: fn(cur.rows) } : cur))

  const patch = async (id: number, body: Parameters<typeof api.updateMilestone>[1]) => {
    try {
      const updated = await api.updateMilestone(id, body)
      setRows((rows) => rows.map((g) => (g.id === updated.id ? updated : g)))
    } catch (err) {
      onError(err)
    }
  }

  const add = async () => {
    const title = newTitle.trim()
    if (!title || !newDate) return
    try {
      const made = await api.createMilestone({
        project_id: projectId,
        title,
        due_date: newDate,
        priority: newPriority,
        kind: newKind,
      })
      setRows((rows) => [...rows, made])
      setNewTitle('')
      setNewDate('')
      setNewPriority('normal')
      setNewKind('other')
      setAdding(false)
      onToast(`Added "${made.title}"`)
    } catch (err) {
      onError(err)
    }
  }

  const remove = async (goal: Milestone) => {
    if (!confirm(`Delete the goal "${goal.title}"?`)) return
    try {
      await api.deleteMilestone(goal.id)
      setRows((rows) => rows.filter((g) => g.id !== goal.id))
      onToast(`Deleted "${goal.title}"`)
    } catch (err) {
      onError(err)
    }
  }

  const span = useMemo(() => spanOf(goals ?? [], now), [goals, now])
  const placed = useMemo(() => placeAll(goals ?? [], span, now), [goals, span, now])
  const nodeName = useMemo(() => new Map(nodes.map((n) => [n.id, n.name])), [nodes])

  if (goals === null) return <p className="loading">Loading timeline…</p>

  const doneCount = goals.filter((g) => g.done).length
  const lateCount = placed.filter((p) => p.state === 'overdue').length
  const soonCount = placed.filter((p) => p.state === 'soon').length
  // Called out separately because these are the dates the team cannot move.
  const saeOpen = goals.filter((g) => g.priority === 'sae' && !g.done).length
  const todayPct = positionOf(now, span)

  // Lanes decide how tall the band has to be; a fixed height either clips a
  // crowded month or leaves a gap when there are three goals all year.
  //
  // The half-band has to fit a whole flag: the label (clamped to two lines by
  // CSS, so this constant stays honest) plus the stem, which grows 64px per
  // lane. Sizing it from the lane count alone clipped the outermost labels.
  // Measured, not guessed: a two-line title plus the date-and-tags meta row
  // comes to 61px. It was 58 before the tags were added, which clipped the
  // outermost label by three pixels.
  const LABEL_H = 64
  const STEM_BASE = 14
  const LANE_STEP = 64
  const laneCount = (side: 'above' | 'below') =>
    placed.filter((p) => p.side === side).reduce((max, p) => Math.max(max, p.lane + 1), 0)
  const deepestLane = Math.max(0, Math.max(laneCount('above'), laneCount('below')) - 1)
  const bandHeight = 2 * (LABEL_H + STEM_BASE + deepestLane * LANE_STEP)

  return (
    <section className="timeline" aria-label="Project timeline">
      <header className="tl-head">
        <h2>
          Timeline <span className="tl-project">{projectName}</span>
        </h2>

        <div className="tl-stats">
          <span>{`${doneCount} of ${goals.length} done`}</span>
          {lateCount > 0 && <span className="tl-stat-late">{`${lateCount} late`}</span>}
          {soonCount > 0 && <span className="tl-stat-soon">{`${soonCount} coming up`}</span>}
          {saeOpen > 0 && (
            <span className="tl-stat-sae">
              {`${saeOpen} Baja SAE deadline${saeOpen === 1 ? '' : 's'}`}
            </span>
          )}
        </div>

        {isAdmin && !adding && (
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setAdding(true)}>
            + Goal
          </button>
        )}
      </header>

      {adding && (
        <div className="tl-add">
          <input
            className="input"
            autoFocus
            placeholder="What has to be done? e.g. Roll cage doc package"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void add()
              if (e.key === 'Escape') setAdding(false)
            }}
          />
          <input
            className="input compact"
            type="date"
            aria-label="Due date"
            value={newDate}
            onChange={(e) => setNewDate(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void add()
              if (e.key === 'Escape') setAdding(false)
            }}
          />
          <select
            className="input compact"
            aria-label="Priority"
            value={newPriority}
            onChange={(e) => setNewPriority(e.target.value as GoalPriority)}
          >
            {PRIORITY_ORDER.map((pr) => (
              <option key={pr} value={pr}>
                {PRIORITY_LABELS[pr]}
              </option>
            ))}
          </select>
          <select
            className="input compact"
            aria-label="Kind of work"
            value={newKind}
            onChange={(e) => setNewKind(e.target.value as GoalKind)}
          >
            {KIND_ORDER.map((k) => (
              <option key={k} value={k}>
                {KIND_LABELS[k]}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={!newTitle.trim() || !newDate}
            onClick={() => void add()}
          >
            Add
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setAdding(false)
              setNewTitle('')
              setNewDate('')
            }}
          >
            Cancel
          </button>
        </div>
      )}

      {goals.length === 0 ? (
        <p className="loading">
          {isAdmin
            ? 'No goals yet. Click “+ Goal” to put the first date on the board.'
            : 'No goals on this timeline yet. A team lead can add them.'}
        </p>
      ) : (
        <>
          {/* Scrolls horizontally rather than compressing: a year squeezed into
              a phone width puts every January date on the same pixel. */}
          <div className="tl-scroll">
            <div className="tl-track" style={{ height: bandHeight }}>
              {span.months.map((m) => (
                <div
                  key={m.getTime()}
                  className="tl-month"
                  style={{ left: `${positionOf(m, span)}%` }}
                >
                  <span className="tl-month-label">
                    {m.toLocaleDateString(undefined, { month: 'short' })}
                    {m.getMonth() === 0 && <em>{` ${m.getFullYear()}`}</em>}
                  </span>
                </div>
              ))}

              <div className="tl-axis" />

              <div className="tl-today" style={{ left: `${todayPct}%` }}>
                <span className="tl-today-label">today</span>
              </div>

              {placed.map(({ milestone, pct, side, lane, atEnd, state }) => (
                <div
                  key={milestone.id}
                  // Labels grow rightwards from their dot, so the last goal
                  // on the axis would hang off the end. Near the end it flips
                  // and grows left instead; the dot and stem do not move.
                  // placeAll decides, so the lane maths accounts for the flip.
                  className={`tl-flag ${side} state-${state} prio-${milestone.priority}${
                    atEnd ? ' at-end' : ''
                  }`}
                  style={{ left: `${pct}%`, ['--lane' as string]: lane }}
                >
                  <button
                    type="button"
                    className="tl-label"
                    title={[
                      milestone.title,
                      `${formatDay(milestone.due_date)} (${dueLabel(milestone, now)})`,
                      PRIORITY_LABELS[milestone.priority],
                      KIND_LABELS[milestone.kind],
                    ].join(' — ')}
                    onClick={() => {
                      if (milestone.node_id != null) onOpenNode(milestone.node_id)
                    }}
                  >
                    <span className="tl-label-title">{milestone.title}</span>
                    {/* One line, never wrapping: the band's height is computed
                        from a constant that assumes a fixed label height. */}
                    <span className="tl-label-meta">
                      <span className="tl-label-date">{formatDay(milestone.due_date)}</span>
                      {PRIORITY_TAGS[milestone.priority] && (
                        <span className={`goal-tag prio-${milestone.priority}`}>
                          {PRIORITY_TAGS[milestone.priority]}
                        </span>
                      )}
                      {KIND_TAGS[milestone.kind] && (
                        <span className="goal-tag kind">{KIND_TAGS[milestone.kind]}</span>
                      )}
                    </span>
                  </button>
                  <span className="tl-stem" />
                  <span className="tl-dot" />
                </div>
              ))}
            </div>
          </div>

          <div className="tl-list">
            {placed.map(({ milestone, state }) => (
              <div
                className={`tl-row state-${state} prio-${milestone.priority}${
                  milestone.done ? ' is-done' : ''
                }`}
                key={milestone.id}
              >
                <input
                  type="checkbox"
                  checked={milestone.done}
                  disabled={!canEdit}
                  aria-label={`Mark "${milestone.title}" done`}
                  title={canEdit ? 'Mark done' : 'Sign in to change this'}
                  onChange={(e) => void patch(milestone.id, { done: e.target.checked })}
                />

                <input
                  className="input tl-row-title"
                  defaultValue={milestone.title}
                  disabled={!canEdit}
                  aria-label="Goal"
                  onBlur={(e) => {
                    const v = e.target.value.trim()
                    if (v && v !== milestone.title) void patch(milestone.id, { title: v })
                    else e.target.value = milestone.title
                  }}
                />

                <input
                  className="input compact"
                  type="date"
                  defaultValue={milestone.due_date}
                  disabled={!canEdit}
                  aria-label="Due date"
                  onChange={(e) => {
                    if (e.target.value) void patch(milestone.id, { due_date: e.target.value })
                  }}
                />

                <select
                  className="input compact tl-row-prio"
                  defaultValue={milestone.priority}
                  disabled={!canEdit}
                  aria-label="Priority"
                  title="How hard this date is. Baja SAE deadlines are set by the organisation and cannot move."
                  onChange={(e) =>
                    void patch(milestone.id, { priority: e.target.value as GoalPriority })
                  }
                >
                  {PRIORITY_ORDER.map((pr) => (
                    <option key={pr} value={pr}>
                      {PRIORITY_LABELS[pr]}
                    </option>
                  ))}
                </select>

                <select
                  className="input compact"
                  defaultValue={milestone.kind}
                  disabled={!canEdit}
                  aria-label="Kind of work"
                  onChange={(e) => void patch(milestone.id, { kind: e.target.value as GoalKind })}
                >
                  {KIND_ORDER.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABELS[k]}
                    </option>
                  ))}
                </select>

                <select
                  className="input compact"
                  defaultValue={milestone.owner_id == null ? '' : String(milestone.owner_id)}
                  disabled={!canEdit}
                  aria-label="Owner"
                  onChange={(e) =>
                    void patch(milestone.id, {
                      owner_id: e.target.value === '' ? null : Number(e.target.value),
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

                <select
                  className="input compact"
                  defaultValue={milestone.node_id == null ? '' : String(milestone.node_id)}
                  disabled={!canEdit}
                  aria-label="Related part"
                  title="Link this goal to a part, so you can jump straight to it"
                  onChange={(e) =>
                    void patch(milestone.id, {
                      node_id: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                >
                  <option value="">No part</option>
                  {nodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name}
                    </option>
                  ))}
                </select>

                <span className="tl-row-due">{dueLabel(milestone, now)}</span>

                {milestone.node_id != null && (
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    title={`Open ${nodeName.get(milestone.node_id) ?? 'the linked part'}`}
                    onClick={() => onOpenNode(milestone.node_id as number)}
                  >
                    Open part
                  </button>
                )}

                {isAdmin && (
                  <button
                    type="button"
                    className="btn btn-sm btn-danger"
                    title="Delete this goal"
                    aria-label={`Delete "${milestone.title}"`}
                    onClick={() => void remove(milestone)}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  )
}
