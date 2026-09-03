import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Member } from '../api/types'

interface Props {
  currentUser: Member | null
  onClose: () => void
  /** Called after any change, so the assignee dropdown picks up new names. */
  onChanged: () => void
  onError: (err: unknown) => void
}

/**
 * Manage Admins.
 *
 * The reason this screen exists: the Cloudflare Access policy is a whole email
 * domain, so everyone with a school address can sign in and read. Who may
 * CHANGE things is decided here instead, in the database, by an existing
 * admin — because team leads rotate every year and next year's lead should not
 * need a terminal, a Fly.io login, or a redeploy to hand over.
 *
 * Deliberately not a roster editor. Members create themselves on first sign-in,
 * so there is nothing to add; the one thing that genuinely needs a human
 * decision is who gets write access.
 */
export function TeamPanel({ currentUser, onClose, onChanged, onError }: Props) {
  const [members, setMembers] = useState<Member[] | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listMembers()
      .then((list) => {
        if (!cancelled) setMembers(list)
      })
      .catch(onError)
    return () => {
      cancelled = true
    }
  }, [onError])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const setAdmin = async (member: Member, next: boolean) => {
    if (
      !next &&
      member.id === currentUser?.id &&
      !confirm(
        'Give up your own admin access?\n\n' +
          'You will still be able to see everything, but you will not be able ' +
          'to change anything — including undoing this.',
      )
    ) {
      return
    }
    setBusyId(member.id)
    try {
      const updated = await api.setMemberAdmin(member.id, next)
      setMembers((cur) =>
        (cur ?? []).map((m) => (m.id === updated.id ? { ...m, is_admin: updated.is_admin } : m)),
      )
      onChanged()
    } catch (err) {
      // Includes the server refusing to demote the last admin. Showing its own
      // message beats guessing at the rule here and drifting out of step.
      onError(err)
    } finally {
      setBusyId(null)
    }
  }

  const admins = (members ?? []).filter((m) => m.is_admin && m.is_active)

  return (
    // The backdrop closes on click; the panel stops propagation so a click
    // inside it does not.
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal team-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="team-panel-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="team-panel-title">Team</h2>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
            Close
          </button>
        </div>

        <p className="modal-note">
          Everyone with a team email can sign in and see everything. Admins are the
          only ones who can add, edit or delete — give it to whoever is leading a
          subsystem this year.
        </p>

        {members === null && <p className="loading">Loading…</p>}

        {members !== null && (
          <div className="team-list">
            {members.map((m) => {
              const isMe = m.id === currentUser?.id
              // The server enforces this too. Disabling it here means the last
              // admin sees why rather than getting an error toast.
              const lastAdmin = m.is_admin && m.is_active && admins.length <= 1
              return (
                <div className={`team-row${m.is_active ? '' : ' inactive'}`} key={m.id}>
                  <div className="team-who">
                    <span className="team-name">
                      {m.name}
                      {isMe && <span className="count">you</span>}
                      {m.is_admin && <span className="admin-pip">admin</span>}
                      {!m.is_active && <span className="count">deactivated</span>}
                    </span>
                    <span className="team-email">{m.email ?? 'no email'}</span>
                  </div>

                  {/* A member who has never signed in has no email and cannot
                      be an admin, because there is no identity to match a
                      verified token against. */}
                  {m.email == null ? (
                    <span className="team-note">never signed in</span>
                  ) : m.is_admin ? (
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={busyId === m.id || lastAdmin}
                      title={
                        lastAdmin
                          ? 'The last admin cannot be removed — promote someone else first.'
                          : 'Remove admin access'
                      }
                      onClick={() => void setAdmin(m, false)}
                    >
                      Remove admin
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      disabled={busyId === m.id || !m.is_active}
                      title={
                        m.is_active
                          ? 'Let this person add, edit and delete'
                          : 'Deactivated members cannot sign in, so they cannot be admins.'
                      }
                      onClick={() => void setAdmin(m, true)}
                    >
                      Make admin
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {members !== null && members.length === 0 && (
          <p className="loading">
            Nobody has signed in yet. Members appear here the first time they open the app.
          </p>
        )}
      </div>
    </div>
  )
}
