import { useEffect, useRef } from 'react'

/**
 * Adds `is-in` to the element once it first scrolls into view, which the
 * stylesheet uses to run the entrance transition.
 *
 * It unobserves after the first hit: these are decorative one-shot entrances,
 * and re-animating a section every time it scrolls back past is the thing that
 * makes a page feel restless.
 *
 * Under prefers-reduced-motion the class goes on immediately and no observer is
 * created — the content must never depend on an animation having run.
 */
export function useReveal<T extends HTMLElement>(delayMs = 0) {
  const ref = useRef<T>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || typeof IntersectionObserver === 'undefined') {
      el.classList.add('is-in')
      return
    }

    // Where the browser has native scroll-driven animations, the stylesheet
    // runs the reveal on the compositor and this observer would be dead weight.
    // Chromium and WebKit take this path; Firefox has not shipped it and falls
    // through to the observer below.
    if (window.CSS?.supports?.('animation-timeline', 'view()')) return

    if (delayMs) el.style.transitionDelay = `${delayMs}ms`

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('is-in')
          io.unobserve(entry.target)
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -60px 0px' },
    )

    io.observe(el)
    return () => io.disconnect()
  }, [delayMs])

  return ref
}
