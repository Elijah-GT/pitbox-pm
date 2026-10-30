import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Countdown as CountdownData } from '../api/types'

const DAY = 86_400_000

const pad = (n: number) => String(n).padStart(2, '0')

/** How loud the timer is: calm a month out, amber inside 30 days, red inside 7. */
function urgency(msLeft: number): 'calm' | 'near' | 'close' | 'here' {
  if (msLeft <= 0) return 'here'
  if (msLeft < 7 * DAY) return 'close'
  if (msLeft < 30 * DAY) return 'near'
  return 'calm'
}

/**
 * The doomsday timer: a live countdown, in the top bar on every section, to
 * the one date the whole team is working towards -- usually competition.
 *
 * Admins set it by clicking it; everyone else just watches it tick. The server
 * enforces that (app/routers/countdown.py); this only decides what to show.
 *
 * A site with PITBOX_DOOMSDAY on shows it as the Doomsday clock instead: big,
 * always red, and called Doomsday, with the admin's name for the date moved to
 * the tooltip. Off, it is the quiet timer that only reddens in the last week.
 */
export function Countdown({
  isAdmin, onError, onToast,
}: {
  isAdmin: boolean
  onError: (err: unknown) => void
  onToast: (message: string) => void
}) {
  const [data, setData] = useState<CountdownData | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .getCountdown()
      .then((d) => {
        if (alive) setData(d)
      })
      // Not worth an error toast on every page load: with no timer the top
      // bar simply shows none. Admins still see the button to set one.
      .catch(() => {
        if (alive) setData({ label: null, at: null, doomsday: false })
      })
    return () => {
      alive = false
    }
  }, [])

  const target = data?.at ? Date.parse(data.at) : null

  // Tick once a second, and only while there is something to count down to.
  useEffect(() => {
    if (target == null) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [target])

  if (data == null) return null

  const doom = data.doomsday
  const name = doom ? 'Doomsday' : 'Countdown'

  const editor = editing && (
    <CountdownEditor
      current={data}
      onClose={() => setEditing(false)}
      onSaved={(next) => {
        setData(next)
        setNow(Date.now())
        setEditing(false)
        onToast(next.at ? `${name} set` : `${name} removed`)
      }}
      onError={onError}
    />
  )

  if (target == null || !data.label) {
    return isAdmin ? (
      <>
        <button type="button" className="btn btn-ghost btn-sm doomsday-set" onClick={() => setEditing(true)}>
          + {name}
        </button>
        {editor}
      </>
    ) : null
  }

  const left = target - now
  const state = urgency(left)
  const clamped = Math.max(0, left)
  const days = Math.floor(clamped / DAY)
  const hours = Math.floor((clamped % DAY) / 3_600_000)
  const minutes = Math.floor((clamped % 3_600_000) / 60_000)
  const seconds = Math.floor((clamped % 60_000) / 1000)
  const when = new Date(target).toLocaleString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit',
  })

  // What the date is, for the tooltip and screen readers. On the Doomsday
  // clock the face only says Doomsday, so this is where "Competition" goes.
  const what = doom && data.label.toLowerCase() !== 'doomsday' ? `Doomsday — ${data.label}` : data.label
  const className = `doomsday is-${state}${doom ? ' is-doomsday' : ''}`

  const face = (
    <>
      <span className="doomsday-label">{doom ? 'Doomsday' : data.label}</span>
      {state === 'here' ? (
        <span className="doomsday-time">NOW</span>
      ) : (
        <span className="doomsday-time">
          {days}
          <small>d</small> {pad(hours)}:{pad(minutes)}:{pad(seconds)}
        </span>
      )}
    </>
  )

  return (
    <>
      {isAdmin ? (
        <button
          type="button"
          className={className}
          title={`${what}: ${when}. Click to change.`}
          aria-label={`${what} in ${days} days. Change the countdown`}
          onClick={() => setEditing(true)}
        >
          {face}
        </button>
      ) : (
        <div className={className} title={`${what}: ${when}`} role="timer" aria-label={`${what} in ${days} days`}>
          {face}
        </div>
      )}
      {editor}
    </>
  )
}

/** The admin's form: a label and a moment, in their own time zone. */
function CountdownEditor({
  current, onClose, onSaved, onError,
}: {
  current: CountdownData
  onClose: () => void
  onSaved: (next: CountdownData) => void
  onError: (err: unknown) => void
}) {
  // datetime inputs speak local time; show the stored instant the same way.
  const start = current.at ? new Date(current.at) : null
  const [label, setLabel] = useState(current.label ?? 'Competition')
  const [date, setDate] = useState(
    start ? `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}` : '',
  )
  const [time, setTime] = useState(start ? `${pad(start.getHours())}:${pad(start.getMinutes())}` : '08:00')
  const [busy, setBusy] = useState(false)
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function save() {
    if (!label.trim() || !date) {
      onError(new Error('The countdown needs a name and a date.'))
      return
    }
    // "2027-05-01T08:00" with no zone is local time in every browser; the ISO
    // string sent to the server carries the exact instant, so everyone counts
    // down to the same second wherever they are.
    const at = new Date(`${date}T${time || '00:00'}`)
    if (Number.isNaN(at.getTime())) {
      onError(new Error('That date or time is not valid.'))
      return
    }
    setBusy(true)
    try {
      onSaved(await api.setCountdown({ label: label.trim(), at: at.toISOString() }))
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!confirm(`Remove the ${current.doomsday ? 'Doomsday clock' : 'countdown'} from the top bar?`)) return
    setBusy(true)
    try {
      await api.clearCountdown()
      onSaved({ label: null, at: null, doomsday: current.doomsday })
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal doomsday-editor"
        role="dialog"
        aria-modal="true"
        aria-label={current.doomsday ? 'Doomsday' : 'Countdown'}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2>{current.doomsday ? 'Doomsday' : 'Countdown'}</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="modal-note">
          {current.doomsday
            ? 'Counts down at the top of every page for everyone, as the Doomsday clock. Name the date — it shows when someone points at the clock.'
            : 'Shown to everyone at the top of every page. Usually competition, but any date the team is working towards.'}
        </p>
        <div className="learn-form">
          <label>
            Counting down to
            <input
              className="input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={60}
              placeholder="Competition"
              autoFocus
            />
          </label>
          <div className="doomsday-when">
            <label>
              Date
              <input className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label>
              Time
              <input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
            </label>
          </div>
          <span className="learn-hint">In your time zone ({zone}). Everyone sees it count down to the same moment.</span>
        </div>
        <div className="learn-editor-foot">
          {current.at && (
            <button type="button" className="btn btn-danger" onClick={() => void remove()} disabled={busy}>
              Remove
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
