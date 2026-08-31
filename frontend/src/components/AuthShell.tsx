import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Wordmark } from './Wordmark'

/**
 * Shared frame for /login and /signup.
 *
 * These forms are deliberately inert. There is no auth backend yet — no users
 * table, no session, no password hashing — so submitting says so plainly rather
 * than pretending. A sign-in box that looks like it works but silently does
 * nothing is worse than no sign-in box: someone will trust it.
 */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="auth">
      <div className="auth-panel">
        <Link to="/" className="site-brand auth-brand">
          <Wordmark />
        </Link>

        <div className="auth-body">
          <h1 className="auth-title">{title}</h1>
          <p className="auth-sub">{subtitle}</p>
          {children}
          <p className="auth-foot">{footer}</p>
        </div>
      </div>

      <aside className="auth-aside" aria-hidden="true">
        <div className="auth-aside-inner">
          <p className="eyebrow">Baja SAE</p>
          <p className="auth-quote">
            Every team runs the same engine. The car is won on everything else.
          </p>
          <div className="auth-tree">
            {['Vehicle', 'Subsystem', 'Assembly', 'Part'].map((level, i) => (
              <div className="auth-tree-row" key={level} style={{ paddingLeft: i * 22 }}>
                <span className="auth-tree-edge" />
                <span className="auth-tree-dot" />
                {level}
              </div>
            ))}
          </div>
        </div>
      </aside>
    </div>
  )
}

/** The banner both forms show on submit. */
export function NotWiredNotice() {
  return (
    <div className="notice" role="status">
      <b>Accounts aren't wired up yet.</b> There is no auth backend behind this form — no
      users table and no session. The tracker is open at <Link to="/app">/app</Link> in the
      meantime.
    </div>
  )
}
