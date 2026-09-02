import type { AuthMode } from '../api/client'
import type { Member, ProjectSummary } from '../api/types'

interface Props {
  projects: ProjectSummary[]
  projectId: number | null
  currentUser: Member | null
  authMode: AuthMode
  onSwitch: (id: number) => void
  onNew: () => void
  onClone: () => void
  onDelete: () => void
  onEditName: () => void
  onSignOut: () => void
}

export function TopBar({
  projects, projectId, currentUser, authMode, onSwitch, onNew, onClone, onDelete, onEditName, onSignOut,
}: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <svg viewBox="0 0 48 48" width="26" height="26" aria-hidden="true">
          <path
            d="M6 34 L18 12 L26 24 L34 14 L42 34 Z"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinejoin="round"
          />
          <circle cx="16" cy="38" r="4" fill="currentColor" />
          <circle cx="34" cy="38" r="4" fill="currentColor" />
        </svg>
        <span>
          Pit <em>Box</em>
        </span>
      </div>

      <select
        className="input"
        aria-label="Select project"
        value={projectId ?? ''}
        onChange={(e) => onSwitch(Number(e.target.value))}
      >
        {/* The node count is here on purpose. Every tree built from the standard
            template has identical subsystem names, so two different trees look
            the same until you expand them — switching between them, or creating
            a new one, otherwise reads as a rename. The count is the one thing
            that visibly differs. */}
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.season ? `${p.name} (${p.season})` : p.name} · {p.node_count}{' '}
            {p.node_count === 1 ? 'node' : 'nodes'}
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
        {/* Sits after the everyday actions and is styled as a danger control, so
            it does not sit next to "Clone" looking like another routine button.
            The handler makes you type the tree's name -- there is no undo. */}
        <button
          type="button"
          className="btn btn-danger"
          onClick={onDelete}
          disabled={projectId == null}
          title="Permanently delete the selected tree"
        >
          Delete tree
        </button>

        {currentUser && (
          // Clickable, because under Cloudflare Access this starts life as
          // whatever the email local part was. The unset state is flagged so a
          // teammate showing as "W1234567" is obviously fixable, not permanent.
          <button
            type="button"
            className={`whoami${currentUser.name_confirmed === false ? ' unnamed' : ''}`}
            title={
              currentUser.name_confirmed === false
                ? 'This name came from your email — click to set your real name'
                : `${currentUser.email ?? ''} — click to change your display name`
            }
            onClick={onEditName}
          >
            {currentUser.name}
            {currentUser.name_confirmed === false && <span className="count">set name</span>}
            {currentUser.is_admin && <span className="admin-pip">admin</span>}
          </button>
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
