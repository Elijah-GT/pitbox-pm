import type { LearnIcon as IconName } from '../api/types'

// The gear's eight teeth, worked out once rather than on every render.
const TEETH = Array.from({ length: 8 }, (_, i) => {
  const a = (i * Math.PI) / 4
  const at = (r: number) => [24 + r * Math.cos(a), 24 + r * Math.sin(a)].map((v) => +v.toFixed(2))
  const [x1, y1] = at(10.5)
  const [x2, y2] = at(15)
  return { x1, y1, x2, y2 }
})

/**
 * Line art for a Learn card, shown until someone uploads a real render. Drawn
 * in currentColor so the card decides the colour, and simple enough to read
 * at the size of a chip.
 */
export function LearnIcon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      className={className ?? 'learn-icon'}
      fill="none"
      stroke="currentColor"
      strokeWidth={2.4}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {name === 'gear' && (
        <>
          <circle cx="24" cy="24" r="9" />
          <circle cx="24" cy="24" r="3.5" />
          {TEETH.map((t, i) => (
            <line key={i} {...t} strokeWidth={4.5} strokeLinecap="butt" />
          ))}
        </>
      )}
      {name === 'spring' && (
        // A coilover: seats top and bottom, the coil between.
        <>
          <path d="M24 3 V9 M15 9 H33" />
          <path d="M17 13 L31 16 L17 19 L31 22 L17 25 L31 28 L17 31 L31 34" />
          <path d="M15 38 H33 M24 38 V45" />
        </>
      )}
      {name === 'wheel' && (
        <>
          <circle cx="24" cy="24" r="16" />
          <circle cx="24" cy="24" r="4" />
          <path d="M8 24 H20 M28 24 H40 M24 28 V40" />
        </>
      )}
      {name === 'weld' && (
        // A torch over a bead of ripples, with a few sparks at the tip.
        <>
          <path d="M7 7 L21 21" strokeWidth={5} />
          <path d="M21 21 L27 27" />
          <path d="M31 25 L34 22 M32 30 H36 M28 32 L29 36" />
          <path d="M5 41 q4 -5 8 0 q4 -5 8 0 q4 -5 8 0 q4 -5 8 0 q4 -5 8 0" />
        </>
      )}
      {name === 'cube' && (
        <>
          <path d="M24 6 L40 15 V33 L24 42 L8 33 V15 Z" />
          <path d="M8 15 L24 24 L40 15 M24 24 V42" />
        </>
      )}
      {name === 'book' && (
        <>
          <path d="M24 12 C19 9 12 9 7 11 V37 C12 35 19 35 24 38 C29 35 36 35 41 37 V11 C36 9 29 9 24 12 Z" />
          <path d="M24 12 V38" />
        </>
      )}
    </svg>
  )
}
