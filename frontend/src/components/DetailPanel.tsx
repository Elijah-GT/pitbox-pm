import { useRef, useState } from 'react'

import { api } from '../api/client'
import type { NodeDetail, Sourcing, Status, Tag, TreeNode } from '../api/types'
import { centsToDollars, formatMoney, humanSize, STATUS_LABELS, STATUS_ORDER } from '../lib/format'
import type { Member } from '../api/types'

interface Props {
  node: NodeDetail
  ancestors: TreeNode[]
  tags: Tag[]
  members: Member[]
  /** Any signed-in member: the fields, tags and uploads are theirs to change. */
  canEdit: boolean
  /** Admin: adding a child and deleting a file. */
  isAdmin: boolean
  onSelect: (id: number) => void
  onAddChild: (node: TreeNode) => void
  onChanged: () => void
  onError: (err: unknown) => void
  onBusy: (message: string) => void
}

export function DetailPanel({
  node,
  ancestors,
  tags,
  members,
  canEdit,
  isAdmin,
  onSelect,
  onAddChild,
  onChanged,
  onError,
  onBusy,
}: Props) {
  // Fields save on blur rather than behind a Save button: in a shop, people edit
  // one field and walk away, and an unsaved form is lost work.
  const save = (patch: Partial<TreeNode>) => {
    api
      .updateNode(node.id, patch)
      .then(onChanged)
      .catch(onError)
  }

  return (
    // Keyed by node id so every uncontrolled input resets when the selection changes.
    <div className="detail" key={node.id}>
      <div className="breadcrumb">
        {ancestors.length === 0 && <span className="sep">Root of this tree</span>}
        {ancestors.map((a, i) => (
          <span key={a.id}>
            {i > 0 && <span className="sep"> / </span>}
            <button type="button" onClick={() => onSelect(a.id)}>
              {a.name}
            </button>
          </span>
        ))}
      </div>

      <div className="detail-title">
        <h1>{node.name}</h1>
        {isAdmin && (
          <button type="button" className="btn btn-sm btn-primary" onClick={() => onAddChild(node)}>
            + Child
          </button>
        )}
      </div>

      <div className="rollups">
        <span>
          Children: <b>{node.child_count}</b>
        </span>
        <span>
          In subtree: <b>{node.descendant_count}</b>
        </span>
        {node.rollup_cost_cents > 0 && (
          <span>
            Subtree cost: <b>{formatMoney(node.rollup_cost_cents)}</b>
          </span>
        )}
        {node.rollup_mass_g > 0 && (
          <span>
            Subtree mass: <b>{`${(node.rollup_mass_g / 1000).toFixed(2)} kg`}</b>
          </span>
        )}
      </div>

      <h3>Details</h3>
      <MetadataForm node={node} members={members} canEdit={canEdit} onSave={save} />

      <h3>Tags</h3>
      <TagSection
        node={node}
        tags={tags}
        canEdit={canEdit}
        onSelect={onSelect}
        onChanged={onChanged}
        onError={onError}
      />

      <h3>{`Files (${node.attachments.length})`}</h3>
      <FileSection
        node={node}
        canEdit={canEdit}
        isAdmin={isAdmin}
        onChanged={onChanged}
        onError={onError}
        onBusy={onBusy}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- metadata */

function MetadataForm({
  node,
  members,
  canEdit,
  onSave,
}: {
  node: NodeDetail
  members: Member[]
  canEdit: boolean
  onSave: (patch: Partial<TreeNode>) => void
}) {
  const text = (
    label: string,
    field: keyof TreeNode,
    value: string | number | null,
    opts: { wide?: boolean; number?: boolean } = {},
  ) => (
    <div className={`field${opts.wide ? ' wide' : ''}`} key={field}>
      <label htmlFor={`f-${field}`}>{label}</label>
      <input
        id={`f-${field}`}
        className="input"
        type={opts.number ? 'number' : 'text'}
        defaultValue={value ?? ''}
        onBlur={(e) => {
          const raw = e.target.value.trim()
          if (opts.number) {
            if (raw === '') return onSave({ [field]: null } as Partial<TreeNode>)
            const num = Number(raw)
            if (Number.isNaN(num)) return
            return onSave({ [field]: num } as Partial<TreeNode>)
          }
          onSave({ [field]: raw === '' ? null : raw } as Partial<TreeNode>)
        }}
      />
    </div>
  )

  // A disabled <fieldset> disables every control inside it, including any added
  // to this form later. That is the point: the alternative is a disabled={} on
  // each of fourteen fields, and a fifteenth that someone forgets.
  return (
    <fieldset className="field-grid" disabled={!canEdit}>
      {text('Name', 'name', node.name, { wide: true })}
      {text('Part number', 'part_number', node.part_number)}

      <div className="field">
        <label htmlFor="f-status">Status</label>
        <select
          id="f-status"
          className="input"
          defaultValue={node.status}
          onChange={(e) => onSave({ status: e.target.value as Status })}
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="f-type">Type</label>
        <select
          id="f-type"
          className="input"
          defaultValue={node.node_type}
          onChange={(e) => onSave({ node_type: e.target.value as TreeNode['node_type'] })}
        >
          <option value="vehicle">Vehicle</option>
          <option value="subsystem">Subsystem</option>
          <option value="assembly">Assembly</option>
          <option value="part">Part</option>
        </select>
      </div>

      <div className="field">
        <label htmlFor="f-assignee">Assignee</label>
        <select
          id="f-assignee"
          className="input"
          defaultValue={node.assignee_id == null ? '' : String(node.assignee_id)}
          onChange={(e) =>
            onSave({ assignee_id: e.target.value === '' ? null : Number(e.target.value) })
          }
        >
          <option value="">Unassigned</option>
          {members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.subteam ? `${m.name} (${m.subteam})` : m.name}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label htmlFor="f-sourcing">Sourcing</label>
        <select
          id="f-sourcing"
          className="input"
          defaultValue={node.sourcing}
          onChange={(e) => onSave({ sourcing: e.target.value as Sourcing })}
        >
          <option value="na">—</option>
          <option value="make">Make</option>
          <option value="buy">Buy</option>
        </select>
      </div>

      {text('Quantity', 'quantity', node.quantity, { number: true })}
      {text('Material', 'material', node.material)}
      {text('Mass (g)', 'mass_g', node.mass_g, { number: true })}
      {text('Vendor', 'vendor', node.vendor)}
      {text('Lead time (days)', 'lead_time_days', node.lead_time_days, { number: true })}

      {/* Cost is stored in integer cents; the form works in dollars. */}
      <div className="field">
        <label htmlFor="f-cost">Unit cost ($)</label>
        <input
          id="f-cost"
          className="input"
          type="number"
          step="0.01"
          defaultValue={centsToDollars(node.cost_cents)}
          onBlur={(e) => {
            const raw = e.target.value.trim()
            if (raw === '') return onSave({ cost_cents: null })
            const dollars = Number(raw)
            if (!Number.isNaN(dollars)) onSave({ cost_cents: Math.round(dollars * 100) })
          }}
        />
      </div>

      <div className="field wide">
        <label htmlFor="f-desc">Description</label>
        <textarea
          id="f-desc"
          defaultValue={node.description ?? ''}
          onBlur={(e) => {
            const raw = e.target.value.trim()
            onSave({ description: raw === '' ? null : raw })
          }}
        />
      </div>
    </fieldset>
  )
}

/* -------------------------------------------------------------------- tags */

function TagSection({
  node,
  tags,
  canEdit,
  onSelect,
  onChanged,
  onError,
}: {
  node: NodeDetail
  tags: Tag[]
  canEdit: boolean
  onSelect: (id: number) => void
  onChanged: () => void
  onError: (err: unknown) => void
}) {
  const [cascade, setCascade] = useState(false)
  const assigned = new Set(node.tags.filter((t) => !t.inherited).map((t) => t.tag_id))
  const hasInherited = node.tags.some((t) => t.inherited)

  return (
    <div>
      <div className="tag-list">
        {node.tags.map((tag) => (
          <span
            key={tag.tag_id}
            className={`tag-pill${tag.inherited ? ' inherited' : ''}`}
            style={tag.inherited ? { color: tag.color } : { background: tag.color }}
            title={tag.inherited ? 'Inherited from an ancestor branch' : undefined}
          >
            {tag.name}
            {tag.inherited ? (
              <button
                type="button"
                title="Go to the node this tag comes from"
                onClick={() => onSelect(tag.source_node_id)}
              >
                ↑
              </button>
            ) : (
              // The "jump to where this tag was set" arrow above is navigation
              // and stays for everyone. This one removes the tag.
              canEdit && (
                <button
                  type="button"
                  title="Remove this tag"
                  aria-label={`Remove tag ${tag.name}`}
                  onClick={() => {
                    api.removeTag(node.id, tag.tag_id).then(onChanged).catch(onError)
                  }}
                >
                  ×
                </button>
              )
            )}
          </span>
        ))}
      </div>

      {canEdit && (
      <div className="tag-list" style={{ marginTop: 8 }}>
        <select
          className="input compact"
          value=""
          aria-label="Add a tag"
          onChange={(e) => {
            if (!e.target.value) return
            api.addTag(node.id, Number(e.target.value), cascade).then(onChanged).catch(onError)
          }}
        >
          <option value="">+ Add tag…</option>
          {tags
            .filter((t) => !assigned.has(t.id))
            .map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
        </select>

        <label
          className="check"
          title="Tag every node beneath this one too — including parts added later."
        >
          <input
            type="checkbox"
            checked={cascade}
            onChange={(e) => setCascade(e.target.checked)}
          />
          <span>apply to whole branch</span>
        </label>
      </div>
      )}

      {hasInherited && (
        <p className="tag-note">
          Dashed tags are inherited from a parent branch. Remove them where they were set.
        </p>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------- files */

function FileSection({
  node,
  canEdit,
  isAdmin,
  onChanged,
  onError,
  onBusy,
}: {
  node: NodeDetail
  canEdit: boolean
  isAdmin: boolean
  onChanged: () => void
  onError: (err: unknown) => void
  onBusy: (message: string) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const upload = (files: FileList | null) => {
    if (!files || files.length === 0) return
    onBusy(`Uploading ${files.length} file(s)…`)
    Promise.all([...files].map((f) => api.upload(node.id, f)))
      .then(onChanged)
      .catch(onError)
  }

  return (
    <div>
      {node.attachments.map((file) => (
        <div className="file-row" key={file.id}>
          <span className="file-kind">{file.kind}</span>
          <a
            className="file-name"
            href={`/api/attachments/${file.id}/download`}
            title="Download"
          >
            {file.filename}
          </a>
          {(file.version > 1 || !file.is_current) && (
            <span className="file-meta">{`v${file.version}${file.is_current ? '' : ' (old)'}`}</span>
          )}
          <span className="file-meta">{humanSize(file.size_bytes)}</span>
          {/* Downloading stays open to anyone who can see the node. Deleting
              is admin-only: re-uploading the same filename makes a new version,
              so a member who picked the wrong file has a fix that destroys
              nothing. */}
          {isAdmin && (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              title="Delete this file"
              onClick={() => {
                if (!confirm(`Delete ${file.filename}?`)) return
                api.deleteAttachment(file.id).then(onChanged).catch(onError)
              }}
            >
              ×
            </button>
          )}
        </div>
      ))}

      {!canEdit && node.attachments.length === 0 && (
        <p className="tag-note">No files on this node.</p>
      )}

      {canEdit && (
      <>
      <button
        type="button"
        className={`dropzone${over ? ' over' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setOver(false)
          upload(e.dataTransfer.files)
        }}
      >
        Drop files here, or click to browse
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        onChange={(e) => {
          upload(e.target.files)
          e.target.value = ''
        }}
      />
      </>
      )}
    </div>
  )
}
