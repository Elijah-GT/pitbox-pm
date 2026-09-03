import { useEffect } from 'react'
import type { MouseEvent } from 'react'

export interface MenuTarget {
  nodeId: number
  name: string
  x: number
  y: number
}

interface Props {
  target: MenuTarget
  /** Admin. Without it the menu offers Rename and nothing else. */
  isAdmin: boolean
  onClose: () => void
  onAddChild: () => void
  onRename: () => void
  onDuplicate: () => void
  onDelete: () => void
}

export function ContextMenu({
  target,
  isAdmin,
  onClose,
  onAddChild,
  onRename,
  onDuplicate,
  onDelete,
}: Props) {
  useEffect(() => {
    const close = () => onClose()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    // Capture phase so a click anywhere dismisses before other handlers run.
    document.addEventListener('click', close)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('click', close)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  const run = (fn: () => void) => (e: MouseEvent) => {
    e.stopPropagation()
    onClose()
    fn()
  }

  // Keep the menu inside the viewport near the right/bottom edges. A member's
  // menu is one item tall, so it does not need the admin menu's clearance.
  const left = Math.min(target.x, window.innerWidth - 210)
  const top = Math.min(target.y, window.innerHeight - (isAdmin ? 180 : 60))

  return (
    <div className="context-menu" style={{ left, top }} onClick={(e) => e.stopPropagation()}>
      {isAdmin && (
        <button type="button" onClick={run(onAddChild)}>
          Add child node
        </button>
      )}
      {/* Renaming a part is editing it, so every member gets this one. */}
      <button type="button" onClick={run(onRename)}>
        Rename
      </button>
      {isAdmin && (
        <>
          <button type="button" onClick={run(onDuplicate)}>
            Duplicate (with subtree)
          </button>
          <hr />
          <button type="button" onClick={run(onDelete)}>
            Delete (with subtree)
          </button>
        </>
      )}
    </div>
  )
}
