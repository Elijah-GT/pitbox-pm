import { useEffect, useRef } from 'react'

/**
 * Conway's Game of Life, rendered as a grid of squares behind the hero.
 *
 * Cells are 10px on a 10px pitch drawn at 9px, so the 1px gutter forms the grid
 * lines for free — no second pass. A cell that has just died is held for four
 * generations at decreasing alpha, which is what turns a twitchy simulation
 * into something that looks like it is breathing. The grid wraps at the edges
 * (a torus), so gliders that run off one side reappear on the other instead of
 * the field slowly emptying.
 *
 * Cost control, in order of how much they matter:
 *   - one generation every GEN_MS, not every frame. rAF still drives it, so the
 *     step lands on a real frame boundary, but 60fps of Life is both wasteful
 *     and too fast to read.
 *   - an IntersectionObserver stops the loop when the hero is scrolled past.
 *     Without it this burns CPU at the bottom of the page forever.
 *   - devicePixelRatio capped at 2, so a 3x phone doesn't render nine times the
 *     pixels for a background texture nobody is inspecting.
 */
const CELL = 10
const GEN_MS = 150
const DENSITY = 0.2
const TRAIL = 4

interface Props {
  /** Base colour as `r, g, b`. Defaults to the brand orange. */
  rgb?: string
  className?: string
}

export function LifeField({ rgb = '255, 106, 26', className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const live = `rgba(${rgb}, 0.30)`
    // Oldest ghost first, so index 0 is the faintest.
    const trail = Array.from({ length: TRAIL }, (_, k) => `rgba(${rgb}, ${((TRAIL - k) / TRAIL) * 0.19})`)

    let cols = 0
    let rows = 0
    let cur = new Uint8Array(0)
    let next = new Uint8Array(0)
    let decay = new Uint8Array(0)
    let width = 0
    let height = 0

    const seed = () => {
      const parent = canvas.parentElement
      if (!parent) return
      width = parent.clientWidth
      height = parent.clientHeight
      if (!width || !height) return

      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      cols = Math.ceil(width / CELL)
      rows = Math.ceil(height / CELL)
      const n = cols * rows
      cur = new Uint8Array(n)
      next = new Uint8Array(n)
      decay = new Uint8Array(n)
      for (let i = 0; i < n; i++) cur[i] = Math.random() < DENSITY ? 1 : 0
    }

    const step = () => {
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          let n = 0
          for (let dy = -1; dy <= 1; dy++) {
            for (let dx = -1; dx <= 1; dx++) {
              if (dx === 0 && dy === 0) continue
              // Modulo wrap on both axes — the field is a torus.
              n += cur[((y + dy + rows) % rows) * cols + ((x + dx + cols) % cols)]
            }
          }

          const i = y * cols + x
          if (cur[i]) {
            next[i] = n === 2 || n === 3 ? 1 : 0
            if (!next[i]) decay[i] = TRAIL // just died: start the ghost
          } else {
            next[i] = n === 3 ? 1 : 0
            if (next[i]) decay[i] = 0
            else if (decay[i] > 0) decay[i] -= 1
          }
        }
      }
      const swap = cur
      cur = next
      next = swap
    }

    const draw = () => {
      ctx.clearRect(0, 0, width, height)

      ctx.fillStyle = live
      for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
          if (cur[y * cols + x]) ctx.fillRect(x * CELL, y * CELL, CELL - 1, CELL - 1)
        }
      }

      // One pass per trail age so fillStyle is set TRAIL times, not per cell.
      for (let age = TRAIL; age >= 1; age--) {
        ctx.fillStyle = trail[TRAIL - age]
        for (let y = 0; y < rows; y++) {
          for (let x = 0; x < cols; x++) {
            const i = y * cols + x
            if (!cur[i] && decay[i] === age) ctx.fillRect(x * CELL, y * CELL, CELL - 1, CELL - 1)
          }
        }
      }
    }

    seed()
    draw()

    // A still field is the whole animation under reduced motion: the texture is
    // decorative, and one frozen generation reads as an intentional pattern.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    let raf = 0
    let last = 0
    let visible = true

    const tick = (t: number) => {
      if (!visible) {
        raf = 0
        return
      }
      if (t - last >= GEN_MS) {
        step()
        draw()
        last = t
      }
      raf = requestAnimationFrame(tick)
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting
        if (visible && !raf) {
          last = 0
          raf = requestAnimationFrame(tick)
        }
      },
      { threshold: 0 },
    )
    io.observe(canvas)
    raf = requestAnimationFrame(tick)

    let resizeTimer: number | undefined
    const onResize = () => {
      window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => {
        seed()
        draw()
      }, 200)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(resizeTimer)
      window.removeEventListener('resize', onResize)
      io.disconnect()
    }
  }, [rgb])

  return <canvas ref={canvasRef} aria-hidden="true" className={className} />
}
