import { useEffect, useRef, useState, type ReactNode } from 'react'

/**
 * A button that opens a short list of actions underneath it.
 *
 * For the actions you need now and then -- sign out, clone a tree -- so they
 * stop occupying the toolbar permanently. Closes on an outside click, on
 * Escape, and after any item is chosen.
 */
export function Menu({
  label,
  buttonClassName = 'btn',
  align = 'right',
  title,
  children,
}: {
  label: ReactNode
  buttonClassName?: string
  /** Which edge of the button the list lines up with. */
  align?: 'left' | 'right'
  title?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="menu" ref={root}>
      <button
        type="button"
        className={buttonClassName}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
      </button>
      {open && (
        // Any click inside -- an item doing its job -- also closes the menu.
        <div className={`menu-pop align-${align}`} role="menu" onClick={() => setOpen(false)}>
          {children}
        </div>
      )}
    </div>
  )
}

export function MenuItem({
  onClick,
  danger,
  disabled,
  children,
}: {
  onClick: () => void
  danger?: boolean
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`menu-item${danger ? ' danger' : ''}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}

export function MenuSeparator() {
  return <hr className="menu-sep" />
}

/** Text at the top of a menu: who you are, what this menu is about. */
export function MenuHeading({ children }: { children: ReactNode }) {
  return (
    // Clicking the heading should not close the menu, unlike an item.
    <div className="menu-head" onClick={(e) => e.stopPropagation()}>
      {children}
    </div>
  )
}
