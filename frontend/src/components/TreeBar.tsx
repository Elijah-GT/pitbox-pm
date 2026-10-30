import type { ProjectSummary } from '../api/types'
import { Menu, MenuItem, MenuSeparator } from './Menu'

interface Props {
  projects: ProjectSummary[]
  projectId: number | null
  /** Admin. New / clone / delete are hidden without it. */
  isAdmin: boolean
  onSwitch: (id: number) => void
  onNew: () => void
  onClone: () => void
  onDelete: () => void
}

/**
 * Which tree you are looking at, and what you can do with a whole tree.
 *
 * Lives at the top of Parts rather than in the app's top bar: picking a tree
 * and managing trees are about the parts breakdown, and having them up there
 * on every section crowded out the navigation. Timeline, Shop and Orders
 * follow whichever tree is chosen here -- their headers name it.
 */
export function TreeBar({ projects, projectId, isAdmin, onSwitch, onNew, onClone, onDelete }: Props) {
  return (
    <div className="treebar">
      <label className="treebar-pick">
        <span className="treebar-label">Tree</span>
        <select
          className="input"
          aria-label="Select tree"
          value={projectId ?? ''}
          onChange={(e) => onSwitch(Number(e.target.value))}
        >
          {/* The node count is here on purpose. Every tree built from the
              standard template has identical subsystem names, so two different
              trees look the same until you expand them -- switching between
              them, or creating a new one, otherwise reads as a rename. The count
              is the one thing that visibly differs. */}
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.season ? `${p.name} (${p.season})` : p.name} · {p.node_count}{' '}
              {p.node_count === 1 ? 'node' : 'nodes'}
            </option>
          ))}
        </select>
      </label>

      <div className="treebar-actions">
        {/* Export stays for everyone: it is a GET, and a member who can read
            the tree on screen can obviously have it as a file. */}
        <a
          className="btn btn-ghost"
          href={projectId == null ? '#' : `/api/projects/${projectId}/export.csv`}
          title="Download this tree's BOM as CSV"
        >
          Export CSV
        </a>

        {/* Hidden rather than disabled for everyone who is not an admin: a
            greyed-out menu reads as "this is broken for me". The server
            refuses these regardless -- see app/security.py. */}
        {isAdmin && (
          <Menu label="Manage ▾" buttonClassName="btn btn-ghost" title="New, clone or delete a tree">
            <MenuItem onClick={onNew}>New tree…</MenuItem>
            <MenuItem onClick={onClone} disabled={projectId == null}>
              Clone this tree for next season…
            </MenuItem>
            <MenuSeparator />
            {/* Last, and red, so it never sits next to Clone looking like
                another routine action. The handler makes you type the tree's
                name -- there is no undo. */}
            <MenuItem onClick={onDelete} danger disabled={projectId == null}>
              Delete this tree…
            </MenuItem>
          </Menu>
        )}
      </div>
    </div>
  )
}
