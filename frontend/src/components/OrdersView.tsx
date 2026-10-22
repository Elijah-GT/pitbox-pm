import { useEffect, useMemo, useState, type FormEvent } from 'react'

import { api } from '../api/client'
import type { Member, OrderStatus, PurchaseRequest } from '../api/types'
import { centsToDollars, formatMoney } from '../lib/format'
import { daysBetween, formatDay, parseDay, today } from '../lib/timeline'

const STATUS_LABELS: Record<OrderStatus, string> = {
  requested: 'Requested',
  approved: 'Approved',
  ordered: 'Ordered',
  shipped: 'Shipped',
  received: 'Received',
  denied: 'Denied',
  cancelled: 'Cancelled',
}
const STATUS_ORDER = Object.keys(STATUS_LABELS) as OrderStatus[]

// Group headings say what the group is waiting on, not just its status --
// "Approved" alone does not tell a lead that these still need ordering.
const GROUP_TITLES: Record<OrderStatus, string> = {
  requested: 'Waiting for approval',
  approved: 'Approved, not yet ordered',
  ordered: 'Ordered',
  shipped: 'Shipped',
  received: 'Received',
  denied: 'Denied',
  cancelled: 'Cancelled',
}

const CLOSED: ReadonlySet<OrderStatus> = new Set(['received', 'denied', 'cancelled'])
const IN_TRANSIT: ReadonlySet<OrderStatus> = new Set(['ordered', 'shipped'])

// Friendlier names for the vendors a Baja team actually orders from, filled in
// from a pasted link. Anything else falls back to the bare hostname.
const KNOWN_VENDORS: Record<string, string> = {
  'mcmaster.com': 'McMaster-Carr',
  'amazon.com': 'Amazon',
  'digikey.com': 'Digi-Key',
  'mouser.com': 'Mouser',
  'grainger.com': 'Grainger',
  'summitracing.com': 'Summit Racing',
  'onlinemetals.com': 'OnlineMetals',
  'speedymetals.com': 'Speedy Metals',
  'aircraftspruce.com': 'Aircraft Spruce',
  'fastenal.com': 'Fastenal',
}

type View = 'open' | 'closed' | 'all'

interface Props {
  projectId: number
  projectName: string
  /** This car's own subsystem names, offered as suggestions. */
  subsystems: string[]
  members: Member[]
  /** Who is signed in -- decides which requests are "yours". */
  currentUserId: number | null
  isAdmin: boolean
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * Purchase requests: anyone asks for a part, leads approve and order it, and
 * whoever opens the box marks it received.
 *
 * The buttons shown here mirror app/routers/orders.py so nobody is offered
 * something that will only be refused -- but they grant nothing. The server
 * checks every change against who is actually signed in.
 */
export function OrdersView({
  projectId, projectName, subsystems, members, currentUserId, isAdmin, onError, onToast,
}: Props) {
  // Keyed by project, so switching trees shows "loading" rather than the
  // previous car's orders for a moment.
  const [loaded, setLoaded] = useState<{ projectId: number; rows: PurchaseRequest[] } | null>(null)
  const rows = loaded && loaded.projectId === projectId ? loaded.rows : null

  const [view, setView] = useState<View>('open')
  const [mineOnly, setMineOnly] = useState(false)
  const [query, setQuery] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .listOrders(projectId)
      .then((list) => {
        if (alive) setLoaded({ projectId, rows: list })
      })
      .catch((err: unknown) => {
        if (alive) onError(err)
      })
    return () => {
      alive = false
    }
  }, [projectId, onError])

  const replace = (row: PurchaseRequest) =>
    setLoaded((prev) =>
      prev ? { ...prev, rows: prev.rows.map((r) => (r.id === row.id ? row : r)) } : prev,
    )

  const memberName = useMemo(() => {
    const byId = new Map(members.map((m) => [m.id, m.name]))
    return (r: PurchaseRequest) =>
      (r.requested_by_id != null ? byId.get(r.requested_by_id) : undefined) ??
      r.history[0]?.by_name ??
      'Unknown'
  }, [members])

  const isMine = (r: PurchaseRequest) => currentUserId != null && r.requested_by_id === currentUserId

  const totals = useMemo(() => {
    const list = rows ?? []
    const sum = (keep: (r: PurchaseRequest) => boolean) =>
      list.filter(keep).reduce((acc, r) => acc + (r.total_cents ?? 0), 0)
    return {
      waiting: sum((r) => r.status === 'requested'),
      approved: sum((r) => r.status === 'approved'),
      onOrder: sum((r) => IN_TRANSIT.has(r.status)),
      received: sum((r) => r.status === 'received'),
      // Said out loud, so an open request with no price cannot make the
      // budget look healthier than it is.
      unpriced: list.filter((r) => !CLOSED.has(r.status) && r.total_cents == null).length,
      open: list.filter((r) => !CLOSED.has(r.status)).length,
      closed: list.filter((r) => CLOSED.has(r.status)).length,
    }
  }, [rows])

  const groups = useMemo(() => {
    if (!rows) return []
    const q = query.trim().toLowerCase()
    const visible = rows.filter(
      (r) =>
        (view === 'all' || (view === 'open') === !CLOSED.has(r.status)) &&
        (!mineOnly || (currentUserId != null && r.requested_by_id === currentUserId)) &&
        (!q ||
          [r.item, r.vendor, r.part_number, r.subsystem, r.notes].some((f) =>
            f?.toLowerCase().includes(q),
          )),
    )
    return STATUS_ORDER.map((status) => ({
      status,
      rows: visible.filter((r) => r.status === status).sort(byNeed),
    })).filter((g) => g.rows.length > 0)
  }, [rows, view, mineOnly, query, currentUserId])

  async function setStatus(r: PurchaseRequest, status: OrderStatus) {
    const extra: { order_number?: string; tracking_number?: string } = {}
    // The two moments a lead has a number in hand. Optional, and Cancel in
    // the prompt cancels the change rather than saving it without one.
    if (status === 'ordered' && isAdmin) {
      const ref = prompt(`Order number for "${r.item}" (optional):`, r.order_number ?? '')
      if (ref === null) return
      if (ref.trim()) extra.order_number = ref.trim()
    }
    if (status === 'shipped' && isAdmin) {
      const ref = prompt(`Tracking number for "${r.item}" (optional):`, r.tracking_number ?? '')
      if (ref === null) return
      if (ref.trim()) extra.tracking_number = ref.trim()
    }
    try {
      replace(await api.updateOrder(r.id, { status, ...extra }))
      onToast(`${r.item}: ${STATUS_LABELS[status].toLowerCase()}`)
    } catch (err) {
      onError(err)
    }
  }

  async function remove(r: PurchaseRequest) {
    if (!confirm(`Delete the request for "${r.item}"? Its history goes with it.`)) return
    try {
      await api.deleteOrder(r.id)
      setLoaded((prev) => (prev ? { ...prev, rows: prev.rows.filter((x) => x.id !== r.id) } : prev))
      onToast('Request deleted')
    } catch (err) {
      onError(err)
    }
  }

  /** The quick actions on a row: what this person can do next, and nothing else. */
  function actionsFor(r: PurchaseRequest): { label: string; status: OrderStatus; primary?: boolean }[] {
    if (isAdmin) {
      switch (r.status) {
        case 'requested':
          return [
            { label: 'Approve', status: 'approved', primary: true },
            { label: 'Deny', status: 'denied' },
          ]
        case 'approved':
          return [{ label: 'Mark ordered', status: 'ordered', primary: true }]
        case 'ordered':
          return [
            { label: 'Mark shipped', status: 'shipped' },
            { label: 'Mark received', status: 'received', primary: true },
          ]
        case 'shipped':
          return [{ label: 'Mark received', status: 'received', primary: true }]
        default:
          return [{ label: 'Reopen', status: 'requested' }]
      }
    }
    if (IN_TRANSIT.has(r.status)) return [{ label: 'Mark received', status: 'received', primary: true }]
    if (r.status === 'requested' && isMine(r)) return [{ label: 'Cancel request', status: 'cancelled' }]
    return []
  }

  const canEditDetails = (r: PurchaseRequest) => isAdmin || (isMine(r) && r.status === 'requested')

  if (!rows) return <p className="loading">Loading orders…</p>

  return (
    <section className="shop orders" aria-label="Purchase requests">
      <div className="shop-head">
        <h2>
          Orders <span className="shop-project">{projectName}</span>
        </h2>
        <div className="shop-stats orders-totals">
          <span title="Requested, not yet approved">
            Waiting <b>{formatMoney(totals.waiting)}</b>
          </span>
          <span title="Approved, not yet ordered">
            Approved <b>{formatMoney(totals.approved)}</b>
          </span>
          <span title="Ordered or shipped">
            On order <b>{formatMoney(totals.onOrder)}</b>
          </span>
          <span title="Received">
            Spent <b>{formatMoney(totals.received)}</b>
          </span>
          {totals.unpriced > 0 && (
            <span className="shop-stat-warn" title="Open requests with no price — not in the totals">
              {totals.unpriced} unpriced
            </span>
          )}
        </div>
      </div>

      {adding ? (
        <OrderForm
          heading="Request a part"
          submitLabel="Send request"
          showOrderFields={false}
          onCancel={() => setAdding(false)}
          onSubmit={async (fields) => {
            const made = await api.createOrder({ project_id: projectId, ...fields })
            setLoaded((prev) => (prev ? { ...prev, rows: [made, ...prev.rows] } : prev))
            setAdding(false)
            setView('open')
            onToast(isAdmin ? 'Request added' : 'Request sent — a team lead will review it')
          }}
          onError={onError}
        />
      ) : (
        <div className="orders-bar">
          <button type="button" className="btn btn-primary" onClick={() => setAdding(true)}>
            + Request a part
          </button>
          <div className="segmented" role="group" aria-label="Which requests">
            {(['open', 'closed', 'all'] as const).map((v) => (
              <button
                key={v}
                type="button"
                className={view === v ? 'active' : ''}
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {v === 'open' ? `Open (${totals.open})` : v === 'closed' ? `Closed (${totals.closed})` : 'All'}
              </button>
            ))}
          </div>
          <label className="check">
            <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
            Only mine
          </label>
          <input
            className="input search"
            type="search"
            placeholder="Search item, vendor, part #…"
            aria-label="Search requests"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}

      {rows.length === 0 && (
        <p className="shop-empty">
          Nothing requested yet. Need something bought? Use <b>Request a part</b> — a team lead
          approves it, and you can follow it here until it arrives.
        </p>
      )}
      {rows.length > 0 && groups.length === 0 && (
        <p className="shop-empty">No requests match.</p>
      )}

      {groups.map((group) => (
        <div key={group.status} className="orders-group">
          <h3 className="shop-group-head">
            {GROUP_TITLES[group.status]}
            <span className="count">{group.rows.length}</span>
          </h3>
          <div className="orders-list">
            {group.rows.map((r) => {
              const open = openId === r.id
              const need = r.needed_by ? needLabel(r.needed_by, CLOSED.has(r.status)) : null
              return (
                <div key={r.id} className={`order-row status-${r.status}${open ? ' is-open' : ''}`}>
                  <button
                    type="button"
                    className="order-summary"
                    aria-expanded={open}
                    onClick={() => {
                      setOpenId(open ? null : r.id)
                      setEditingId(null)
                    }}
                  >
                    <span className={`order-pill status-${r.status}`}>{STATUS_LABELS[r.status]}</span>
                    <span className="order-item">
                      <span className="order-name">{r.item}</span>
                      <span className="order-sub">
                        {/* A non-breaking space, so a row with no vendor is
                            as tall as one with -- a plain space collapses. */}
                        {[r.vendor, r.part_number, r.subsystem].filter(Boolean).join(' · ') || ' '}
                      </span>
                    </span>
                    <span className="order-cost">
                      <b>{r.total_cents != null ? formatMoney(r.total_cents) : 'no price'}</b>
                      <span className="order-sub">
                        {r.quantity} × {r.unit_cost_cents != null ? formatMoney(r.unit_cost_cents) : '?'}
                      </span>
                    </span>
                    <span className={`order-need${need?.late ? ' is-late' : ''}`}>{need?.text ?? ''}</span>
                    <span className="order-who">{memberName(r)}</span>
                  </button>
                  <div className="order-actions">
                    {actionsFor(r).map((a) => (
                      <button
                        key={a.status}
                        type="button"
                        className={`btn btn-sm${a.primary ? ' btn-primary' : ''}`}
                        onClick={() => void setStatus(r, a.status)}
                      >
                        {a.label}
                      </button>
                    ))}
                  </div>

                  {open && editingId !== r.id && (
                    <OrderDetail
                      row={r}
                      isAdmin={isAdmin}
                      canEdit={canEditDetails(r)}
                      onEdit={() => setEditingId(r.id)}
                      onStatus={(s) => void setStatus(r, s)}
                      onDelete={() => void remove(r)}
                    />
                  )}
                  {open && editingId === r.id && (
                    <OrderForm
                      heading="Edit request"
                      submitLabel="Save"
                      initial={r}
                      // A member never sends these keys at all: the server
                      // refuses a member's edit that so much as mentions them.
                      showOrderFields={isAdmin}
                      onCancel={() => setEditingId(null)}
                      onSubmit={async (fields) => {
                        replace(await api.updateOrder(r.id, fields))
                        setEditingId(null)
                        onToast('Request updated')
                      }}
                      onError={onError}
                    />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      <datalist id="order-subsystems">
        {subsystems.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
    </section>
  )
}

/** Soonest need first, undated after dated, then the longest-waiting first. */
function byNeed(a: PurchaseRequest, b: PurchaseRequest): number {
  if (a.needed_by !== b.needed_by) {
    if (!a.needed_by) return 1
    if (!b.needed_by) return -1
    return a.needed_by < b.needed_by ? -1 : 1
  }
  return a.created_at < b.created_at ? -1 : 1
}

function needLabel(iso: string, closed: boolean): { text: string; late: boolean } {
  if (closed) return { text: `needed ${formatDay(iso)}`, late: false }
  const left = daysBetween(today(), parseDay(iso))
  if (left < 0) return { text: `${-left} day${left === -1 ? '' : 's'} late`, late: true }
  if (left === 0) return { text: 'needed today', late: true }
  if (left === 1) return { text: 'needed tomorrow', late: false }
  if (left < 14) return { text: `needed in ${left} days`, late: false }
  return { text: `needed by ${formatDay(iso)}`, late: false }
}

/* ---------------------------------------------------------------- detail */

function OrderDetail({
  row, isAdmin, canEdit, onEdit, onStatus, onDelete,
}: {
  row: PurchaseRequest
  isAdmin: boolean
  canEdit: boolean
  onEdit: () => void
  onStatus: (status: OrderStatus) => void
  onDelete: () => void
}) {
  // The server only stores http(s) links; checked again here because this
  // becomes a real href.
  const link = row.url && /^https?:\/\//i.test(row.url) ? row.url : null

  return (
    <div className="order-detail">
      <dl className="order-facts">
        {link && (
          <>
            <dt>Link</dt>
            <dd>
              <a href={link} target="_blank" rel="noopener noreferrer">
                {hostOf(link)} ↗
              </a>
            </dd>
          </>
        )}
        {row.notes && (
          <>
            <dt>Why</dt>
            <dd className="order-notes">{row.notes}</dd>
          </>
        )}
        {row.order_number && (
          <>
            <dt>Order #</dt>
            <dd>{row.order_number}</dd>
          </>
        )}
        {row.tracking_number && (
          <>
            <dt>Tracking</dt>
            <dd>{row.tracking_number}</dd>
          </>
        )}
      </dl>

      <ol className="order-history" aria-label="History">
        {row.history.map((e, i) => (
          <li key={i}>
            <span className={`order-pill status-${e.status}`}>{STATUS_LABELS[e.status]}</span>
            <span>
              {e.by_name ?? 'Someone'} · {new Date(e.at).toLocaleString(undefined, {
                month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
              })}
            </span>
          </li>
        ))}
      </ol>

      <div className="order-detail-actions">
        {canEdit && (
          <button type="button" className="btn btn-sm" onClick={onEdit}>
            Edit details
          </button>
        )}
        {isAdmin && (
          <label className="order-set-status">
            Set status
            <select
              className="input"
              value={row.status}
              onChange={(e) => onStatus(e.target.value as OrderStatus)}
            >
              {STATUS_ORDER.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
        )}
        {isAdmin && (
          <button type="button" className="btn btn-sm btn-danger" onClick={onDelete}>
            Delete
          </button>
        )}
      </div>
    </div>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** "mcmaster.com/91251A540" -> "https://mcmaster.com/91251A540". */
function withScheme(raw: string): string {
  const url = raw.trim()
  if (!url || /^[a-z][a-z0-9+.-]*:/i.test(url)) return url
  return `https://${url}`
}

function vendorFromUrl(raw: string): string | null {
  try {
    const host = new URL(withScheme(raw)).hostname.replace(/^www\./, '')
    return KNOWN_VENDORS[host] ?? host
  } catch {
    return null
  }
}

/** Dollars as typed -- "$1,250.5" -- to cents. undefined means "not a price". */
function parseDollars(raw: string): number | null | undefined {
  const s = raw.replace(/[$,\s]/g, '')
  if (!s) return null
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return undefined
  return Math.round(Number(s) * 100)
}

/* ------------------------------------------------------------------ form */

interface OrderFields {
  item: string
  url: string | null
  vendor: string | null
  part_number: string | null
  quantity: number
  unit_cost_cents: number | null
  subsystem: string | null
  needed_by: string | null
  notes: string | null
  order_number?: string | null
  tracking_number?: string | null
}

function OrderForm({
  heading, submitLabel, initial, showOrderFields, onSubmit, onCancel, onError,
}: {
  heading: string
  submitLabel: string
  initial?: PurchaseRequest
  /** Order and tracking numbers: leads only. */
  showOrderFields: boolean
  onSubmit: (fields: OrderFields) => Promise<void>
  onCancel: () => void
  onError: (err: unknown) => void
}) {
  const [item, setItem] = useState(initial?.item ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  const [vendor, setVendor] = useState(initial?.vendor ?? '')
  const [partNumber, setPartNumber] = useState(initial?.part_number ?? '')
  const [quantity, setQuantity] = useState(String(initial?.quantity ?? 1))
  const [price, setPrice] = useState(centsToDollars(initial?.unit_cost_cents ?? null))
  const [subsystem, setSubsystem] = useState(initial?.subsystem ?? '')
  const [neededBy, setNeededBy] = useState(initial?.needed_by ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [orderNumber, setOrderNumber] = useState(initial?.order_number ?? '')
  const [tracking, setTracking] = useState(initial?.tracking_number ?? '')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const qty = Number(quantity)
  const cents = parseDollars(price)
  const total = cents != null && Number.isInteger(qty) && qty > 0 ? cents * qty : null

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!item.trim()) return setProblem('Say what you want bought.')
    if (!Number.isInteger(qty) || qty < 1) return setProblem('Quantity has to be a whole number, 1 or more.')
    if (cents === undefined) return setProblem('Price should look like 12.50 — dollars and cents.')
    setProblem(null)

    const blank = (s: string) => s.trim() || null
    const fields: OrderFields = {
      item: item.trim(),
      url: blank(withScheme(url)),
      // Also filled here, not only when the Link box loses focus: paste a
      // link and press Enter and the form submits without that ever happening.
      vendor: blank(vendor) ?? (url.trim() ? vendorFromUrl(url) : null),
      part_number: blank(partNumber),
      quantity: qty,
      unit_cost_cents: cents,
      subsystem: blank(subsystem),
      needed_by: neededBy || null,
      notes: blank(notes),
    }
    if (showOrderFields) {
      fields.order_number = blank(orderNumber)
      fields.tracking_number = blank(tracking)
    }

    setBusy(true)
    try {
      await onSubmit(fields)
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="order-form" onSubmit={(e) => void submit(e)}>
      <h3 className="shop-group-head">{heading}</h3>
      <div className="order-form-grid">
        <label className="span-2">
          What do you need?
          <input
            className="input"
            value={item}
            onChange={(e) => setItem(e.target.value)}
            placeholder="e.g. 3/8-24 jam nuts, Fox shock rebuild kit"
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
            // Fill the vendor from the link when it is still empty -- pasting
            // a McMaster URL should not mean typing "McMaster-Carr" as well.
            onBlur={() => {
              if (!vendor.trim() && url.trim()) setVendor(vendorFromUrl(url) ?? '')
            }}
            placeholder="Paste the product page"
            inputMode="url"
          />
        </label>
        <label>
          Vendor
          <input className="input" value={vendor} onChange={(e) => setVendor(e.target.value)} maxLength={120} />
        </label>
        <label>
          Part #
          <input
            className="input"
            value={partNumber}
            onChange={(e) => setPartNumber(e.target.value)}
            maxLength={120}
          />
        </label>
        <label>
          Quantity
          <input
            className="input"
            type="number"
            min={1}
            step={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </label>
        <label>
          Price each ($)
          <input
            className="input"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="0.00"
            inputMode="decimal"
          />
        </label>
        <label>
          Subsystem
          <input
            className="input"
            value={subsystem}
            onChange={(e) => setSubsystem(e.target.value)}
            list="order-subsystems"
            maxLength={80}
          />
        </label>
        <label>
          Needed by
          <input className="input" type="date" value={neededBy} onChange={(e) => setNeededBy(e.target.value)} />
        </label>
        {showOrderFields && (
          <>
            <label>
              Order #
              <input
                className="input"
                value={orderNumber}
                onChange={(e) => setOrderNumber(e.target.value)}
                maxLength={120}
              />
            </label>
            <label>
              Tracking #
              <input className="input" value={tracking} onChange={(e) => setTracking(e.target.value)} maxLength={120} />
            </label>
          </>
        )}
        <label className="span-all">
          Why is it needed?
          <textarea
            className="input"
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What it is for — the first thing whoever approves it will want to know"
            maxLength={4000}
          />
        </label>
      </div>
      <div className="order-form-foot">
        {problem && <span className="order-problem">{problem}</span>}
        {total != null && total > 0 && <span className="order-form-total">Total {formatMoney(total)}</span>}
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
