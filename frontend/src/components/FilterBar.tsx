import { useState } from 'react'

import type { Member, Status, Tag } from '../api/types'
import { emptyFilter, type FilterState } from '../lib/filter'
import { STATUS_LABELS, STATUS_ORDER } from '../lib/format'

interface Props {
  tags: Tag[]
  members: Member[]
  filter: FilterState
  matchedCount: number
  totalCount: number
  filterActive: boolean
  onChange: (next: FilterState) => void
}

export function FilterBar({
  tags,
  members,
  filter,
  matchedCount,
  totalCount,
  filterActive,
  onChange,
}: Props) {
  // Collapsed on a phone, where the tag chips alone wrapped to five rows and
  // pushed the tree -- the actual point of the page -- off the bottom. On a
  // wide screen `.filter-rest` is `display: contents`, so the desktop layout is
  // exactly what it was and this state does nothing.
  const [open, setOpen] = useState(false)

  const activeCount =
    filter.tags.size +
    (filter.query ? 1 : 0) +
    (filter.status ? 1 : 0) +
    (filter.assigneeId !== '' ? 1 : 0) +
    (filter.includeDescendants ? 1 : 0)

  const patch = (partial: Partial<FilterState>) => onChange({ ...filter, ...partial })

  const toggleTag = (slug: string) => {
    const next = new Set(filter.tags)
    if (next.has(slug)) next.delete(slug)
    else next.add(slug)
    patch({ tags: next })
  }

  return (
    <section className={`filterbar${open ? ' open' : ''}`} aria-label="Filters">
      <button
        type="button"
        className="btn filter-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        Filters
        {activeCount > 0 && <span className="count">{activeCount}</span>}
      </button>

      <input
        className="input search"
        type="search"
        placeholder="Search name, part number, vendor, description…"
        value={filter.query}
        onChange={(e) => patch({ query: e.target.value.trim().toLowerCase() })}
      />

      <div className="filter-rest">
      <div className="filter-group">
        <span className="filter-label">Tags</span>
        <div className="chips" role="group" aria-label="Filter by tag">
          {tags.map((tag) => {
            const active = filter.tags.has(tag.slug)
            return (
              <button
                key={tag.id}
                type="button"
                className="chip"
                aria-pressed={active}
                title={tag.category ?? undefined}
                style={active ? { background: tag.color } : undefined}
                onClick={() => toggleTag(tag.slug)}
              >
                <span
                  className="dot"
                  style={{ background: active ? 'rgba(0,0,0,.45)' : tag.color }}
                />
                {tag.name}
                {tag.node_count > 0 && <span className="count">{tag.node_count}</span>}
              </button>
            )
          })}
        </div>
      </div>

      <div className="filter-group">
        <span className="filter-label">Match</span>
        <div className="segmented" role="group" aria-label="Tag match mode">
          {(['any', 'all'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={filter.tagMode === mode ? 'active' : ''}
              aria-pressed={filter.tagMode === mode}
              onClick={() => patch({ tagMode: mode })}
            >
              {mode === 'any' ? 'Any' : 'All'}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-group">
        {/* Isolate hides everything not on the path to a match; Highlight keeps
            the whole tree and dims the misses — better for seeing WHERE
            matches sit in the car. */}
        <span className="filter-label">View</span>
        <div className="segmented" role="group" aria-label="Filter display mode">
          {(['isolate', 'highlight'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={filter.mode === mode ? 'active' : ''}
              aria-pressed={filter.mode === mode}
              onClick={() => patch({ mode })}
            >
              {mode === 'isolate' ? 'Isolate' : 'Highlight'}
            </button>
          ))}
        </div>
      </div>

      <select
        className="input compact"
        aria-label="Filter by status"
        value={filter.status}
        onChange={(e) => patch({ status: e.target.value as Status | '' })}
      >
        <option value="">Any status</option>
        {STATUS_ORDER.map((s) => (
          <option key={s} value={s}>
            {STATUS_LABELS[s]}
          </option>
        ))}
      </select>

      <select
        className="input compact"
        aria-label="Filter by assignee"
        value={filter.assigneeId === '' ? '' : String(filter.assigneeId)}
        onChange={(e) => patch({ assigneeId: e.target.value === '' ? '' : Number(e.target.value) })}
      >
        <option value="">Anyone</option>
        {members.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>

      <label className="check" title="Also show everything beneath a matching node">
        <input
          type="checkbox"
          checked={filter.includeDescendants}
          onChange={(e) => patch({ includeDescendants: e.target.checked })}
        />
        <span>+ subtree</span>
      </label>

      <button
        type="button"
        className="btn btn-ghost"
        onClick={() => onChange({ ...emptyFilter, mode: filter.mode, tags: new Set() })}
      >
        Clear
      </button>

      <span className="filter-count" aria-live="polite">
        {filterActive ? `${matchedCount} of ${totalCount} nodes match` : `${totalCount} nodes`}
      </span>
      </div>
    </section>
  )
}
