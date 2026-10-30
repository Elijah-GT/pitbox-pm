import type { AuthMode } from '../api/client'
import type { Member } from '../api/types'
import { Countdown } from './Countdown'
import { Menu, MenuHeading, MenuItem, MenuSeparator } from './Menu'

/**
 * The sections of the app. The first four are over the tree chosen in Parts:
 * what the car is made of, when things are due, what the shop has to make,
 * and what has to be bought. Learn and Resources are team-wide, with no tree.
 */
export type Workspace = 'breakdown' | 'timeline' | 'shop' | 'orders' | 'learn' | 'resources'

const WORKSPACE_LABELS: Record<Workspace, string> = {
  breakdown: 'Parts',
  timeline: 'Timeline',
  shop: 'Shop',
  orders: 'Orders',
  learn: 'Learn',
  resources: 'Resources',
}
const WORKSPACE_ORDER = Object.keys(WORKSPACE_LABELS) as Workspace[]

interface Props {
  currentUser: Member | null
  authMode: AuthMode
  isAdmin: boolean
  /** Which section of the app is on screen. */
  workspace: Workspace
  onWorkspace: (next: Workspace) => void
  onEditName: () => void
  onManageTeam: () => void
  onSignOut: () => void
  onError: (err: unknown) => void
  onToast: (message: string) => void
}

/**
 * Where you are, who you are, and how long is left -- nothing else.
 *
 * It used to carry the tree picker and every tree action as well, which made
 * it the most crowded row in the app and put tree controls on screens that
 * have no tree. Those now live at the top of Parts (TreeBar); the rarely used
 * account actions live behind your name.
 */
export function TopBar({
  currentUser, authMode, isAdmin, workspace, onWorkspace, onEditName, onManageTeam, onSignOut,
  onError, onToast,
}: Props) {
  // Under Cloudflare Access a name starts life as the email's local part. The
  // unset state is flagged on the button itself, so a teammate showing as
  // "W1234567" sees it is fixable without opening anything.
  const unnamed = currentUser?.name_confirmed === false

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
          Car<em>Hub</em>
        </span>
      </div>

      <nav className="workspace-switch" aria-label="Sections">
        {WORKSPACE_ORDER.map((w) => (
          <button
            key={w}
            type="button"
            className={workspace === w ? 'active' : ''}
            aria-current={workspace === w ? 'page' : undefined}
            onClick={() => onWorkspace(w)}
          >
            {WORKSPACE_LABELS[w]}
          </button>
        ))}
      </nav>

      <div className="topbar-actions">
        {/* Waits for /api/auth/me, like the account button: an admin's
            "set it" control must not flash up for members while loading. */}
        {currentUser && <Countdown isAdmin={isAdmin} onError={onError} onToast={onToast} />}

        {/* Only once /api/auth/me has answered: until then we do not know who
            this is, and the button should not appear and then change. */}
        {currentUser && (
          <Menu
            buttonClassName={`whoami${unnamed ? ' unnamed' : ''}`}
            title={unnamed ? 'This name came from your email — set your real name' : 'Your account'}
            label={
              <>
                <span className="whoami-name">{currentUser.name}</span>
                {unnamed && <span className="count">set name</span>}
                {isAdmin && <span className="admin-pip">admin</span>}
                <span className="whoami-caret" aria-hidden="true">
                  ▾
                </span>
              </>
            }
          >
            <MenuHeading>
              <strong>{currentUser.name}</strong>
              {currentUser.email && <span>{currentUser.email}</span>}
              {/* Says what your role can do, so a member who finds no Delete
                  button does not file it as a bug. It does NOT say "view
                  only" -- members edit parts every day. */}
              {authMode !== 'none' && (
                <span className="menu-role">
                  {isAdmin
                    ? 'Admin: you can also add, delete and manage trees, approve orders and edit Learn.'
                    : 'Member: you can edit parts, goals and the shop list, and request orders.'}
                </span>
              )}
            </MenuHeading>
            <MenuItem onClick={onEditName}>{unnamed ? 'Set your name…' : 'Change display name…'}</MenuItem>
            {isAdmin && <MenuItem onClick={onManageTeam}>Team & admins…</MenuItem>}
            {/* auth_mode=none has nothing to sign out of. Under Cloudflare
                Access the session belongs to Cloudflare, so this hands off to
                their logout endpoint rather than pretending the app owns it. */}
            {authMode !== 'none' && (
              <>
                <MenuSeparator />
                <MenuItem onClick={onSignOut}>Sign out</MenuItem>
              </>
            )}
          </Menu>
        )}
      </div>
    </header>
  )
}
