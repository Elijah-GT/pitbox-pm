import { useCallback, useLayoutEffect, useRef, useState } from 'react'

/**
 * Drives a pinned hero. `.hero` is tall; `.hero-stage` sticks to the viewport
 * for its whole length, so scrolling moves nothing on screen — it only feeds a
 * 0..1 progress number into `--p`, which the stylesheet reads to dissolve the
 * wordmark. That separation is the whole trick: the animation is a pure
 * function of scroll position, so it is scrubbable, interruptible, and never
 * fights the browser's own scrolling.
 *
 * Progress is written straight to the DOM node rather than through state — at
 * 60fps a `setState` per frame would re-render the entire landing page.
 *
 * It also marks `<html data-hero>` so the nav knows whether the big wordmark is
 * still on screen; the nav's own small one stays hidden until it is not.
 */
export function useHeroScroll() {
  const sectionRef = useRef<HTMLElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  /** Same 0..1 the CSS gets, for consumers that cannot read a custom property
      cheaply every frame — the WebGL scene reads this instead of calling
      getComputedStyle at 60fps. */
  const progressRef = useRef(0)
  /** Consumers that must redraw when progress changes. A plain ref is not
      enough on its own: child effects run before parent effects, so a child
      listening to `scroll` itself is registered first and would read progress
      from the previous scroll position. Pushing the value guarantees every
      consumer draws the progress that actually applies. */
  const [listeners] = useState(() => new Set<(p: number) => void>())

  const subscribe = useCallback(
    (fn: (p: number) => void) => {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
    [listeners],
  )

  useLayoutEffect(() => {
    const section = sectionRef.current
    const stage = stageRef.current
    if (!section || !stage) return

    const root = document.documentElement

    // No scroll choreography under reduced motion: show the mark, and leave the
    // nav brand permanently visible so it can never be missing.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      stage.style.setProperty('--p', '0')
      progressRef.current = 0
      listeners.forEach((fn) => fn(0))
      root.dataset.hero = 'passed'
      return () => {
        delete root.dataset.hero
      }
    }

    root.dataset.hero = 'active'
    let raf = 0

    const update = () => {
      raf = 0
      const travel = section.offsetHeight - window.innerHeight
      const scrolled = -section.getBoundingClientRect().top
      const p = travel <= 0 ? 0 : Math.min(Math.max(scrolled / travel, 0), 1)

      stage.style.setProperty('--p', p.toFixed(4))
      progressRef.current = p
      listeners.forEach((fn) => fn(p))
      // Just past SPIN_END in HeroCar3D (0.42), where the turn lands side-on
      // and the car starts its exit — so the header fills in behind a car that
      // is already leaving, not one still turning in the middle of the stage.
      root.dataset.hero = p > 0.5 ? 'passed' : 'active'
    }

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }

    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
      delete root.dataset.hero
    }
  }, [listeners])

  return { sectionRef, stageRef, progressRef, subscribe }
}
