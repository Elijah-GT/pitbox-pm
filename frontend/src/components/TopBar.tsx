import type { AuthMode } from '../api/client'
import type { Member, ProjectSummary } from '../api/types'
import { Wordmark } from './Wordmark'

interface Props {
  projects: ProjectSummary[]
  projectId: number | null
  currentUser: Member | null
  authMode: AuthMode
  onSwitch: (id: number) => void
  onNew: () => void
  onClone: () => void
  onSignOut: () => void
}

export function TopBar({
  projects, projectId, currentUser, authMode, onSwitch, onNew, onClone, onSignOut,
}: Props) {
  return (
    <header className="topbar">
      {/* The same mark as the public pages — one component, so the app and
          the landing page cannot drift apart. */}
      <div className="brand">
        <Wordmark />
      </div>

      <select
        className="input"
        aria-label="Select project"
        value={projectId ?? ''}
        onChange={(e) => onSwitch(Number(e.target.value))}
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.season ? `${p.name} (${p.season})` : p.name}
          </option>
        ))}
      </select>

      <div className="topbar-actions">
        <button type="button" className="btn" onClick={onNew} title="Create a new tree">
          + New Tree
        </button>
        <button
          type="button"
          className="btn"
          onClick={onClone}
          title="Start next year from this car"
          disabled={projectId == null}
        >
          Clone
        </button>
        <a
          className="btn"
          href={projectId == null ? '#' : `/api/projects/${projectId}/export.csv`}
          title="Download the BOM as CSV"
        >
          Export CSV
        </a>
        <a className="btn btn-ghost" href="/docs" target="_blank" rel="noopener">
          API
        </a>

        {currentUser && (
          <span className="whoami" title={currentUser.email ?? undefined}>
            {currentUser.name}
            {currentUser.is_admin && <span className="admin-pip">admin</span>}
          </span>
        )}
        {/* auth_mode=none has nothing to sign out of. Under Cloudflare Access
            the session belongs to Cloudflare, so the button hands off to their
            logout endpoint rather than pretending the app owns it. */}
        {authMode !== 'none' && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={onSignOut}
            title={authMode === 'cloudflare' ? 'Signs you out of Cloudflare Access' : undefined}
          >
            Sign out
          </button>
        )}
      </div>
    </header>
  )
}
