import { useLayoutEffect, useRef } from 'react'

/**
 * The under-page footer.
 *
 * The footer is fixed at the bottom of the viewport, behind the page, and the
 * page carries an opaque background over the top of it. A spacer the height of
 * the footer sits at the end of the document, so the last stretch of scrolling
 * slides the page up and uncovers what was underneath all along — the footer
 * itself never moves. It fades from transparent to opaque across that reveal.
 *
 * Two custom properties do the work, both written straight to the DOM rather
 * than through state: `--foot-h` (measured, so the spacer always matches the
 * real footer) and `--footp` (0..1 revealed).
 *
 * The height is measured with a ResizeObserver, not once on mount: the footer
 * reflows with the viewport, and a stale height leaves either a gap below the
 * page or a footer that can never be fully uncovered.
 */
export function useFooterReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return

    const root = document.documentElement
    let raf = 0
    let height = 0

    const update = () => {
      raf = 0
      // Distance still to scroll. The spacer is the last `height` pixels of it,
      // so progress through that stretch is progress through the reveal.
      const max = root.scrollHeight - window.innerHeight
      const p = height > 0 ? (window.scrollY - (max - height)) / height : 1
      root.style.setProperty('--footp', Math.min(Math.max(p, 0), 1).toFixed(3))
    }

    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update)
    }

    const ro = new ResizeObserver(() => {
      height = el.offsetHeight
      root.style.setProperty('--foot-h', `${height}px`)
      update()
    })
    ro.observe(el)

    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      ro.disconnect()
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      if (raf) cancelAnimationFrame(raf)
      root.style.removeProperty('--foot-h')
      root.style.removeProperty('--footp')
    }
  }, [])

  return ref
}
