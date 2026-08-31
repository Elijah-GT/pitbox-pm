import { useEffect, useRef, type RefObject } from 'react'

const FRAMES = 60
/** Front three-quarter-on view: the car looking straight at the viewer. */
const FRONT = 5
/** Clean side profile. Rotating +90deg from FRONT puts the nose at screen
 *  right, so this frame faces RIGHT and the car must depart to the right —
 *  going the other way drives it in reverse. */
const PROFILE = 20
const DEPART_DIR = 1
/** Fraction of the hero scroll spent turning; the rest is the drive-off. */
const SPIN_END = 0.66
/** Extra rotation spent during the drive-off, on top of the turn to profile. */
const EXIT_TURNS = 1
/** Load-in: the car spins up and settles facing the viewer. */
const INTRO_MS = 2300
const INTRO_TURNS = 1.5
/** Unveil: the car is drawn dark and a light front travels up it. Slightly
 *  longer than the spin so the light lands just after the car settles. */
const UNVEIL_MS = 2600
const UNVEIL_DELAY = 250

const frameSrc = (i: number) => `/car/car-${String(i).padStart(3, '0')}.webp`
const clamp01 = (n: number) => Math.min(Math.max(n, 0), 1)
/** Ease OUT only: the spin starts at full speed and coasts down to rest. An
 *  ease-in would have it creep away from a standstill, which reads as lag
 *  rather than momentum. */
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3)

/**
 * The hero car as a pre-rendered turntable scrubbed on a 2D canvas — the
 * technique Apple's product pages use.
 *
 * This replaced a WebGL/three.js version that worked in Chromium, WebKit and
 * Gecko but died on a real machine with `webglcontextlost`: Safari caps how
 * many live WebGL contexts it will keep and drops them under tab pressure, and
 * there is nothing a page can do about that. Frames have no such failure mode —
 * every viewer sees identical, correctly-lit pixels, and the cost is bandwidth
 * rather than GPU state.
 */
export function HeroCarFrames({
  progress,
  subscribe,
}: {
  progress: RefObject<number>
  subscribe: (fn: (p: number) => void) => () => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const wrap = wrapRef.current
    const canvas = canvasRef.current
    if (!wrap || !canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const images = new Array<HTMLImageElement | null>(FRAMES).fill(null)
    let raf = 0
    let stopped = false
    // The size the canvas was last laid out at. Kept in the closure so paint()
    // and the backing store can never disagree about the drawing surface.
    let cssW = 0
    let cssH = 0
    let introRaf = 0
    // Skip the load-in if the page was restored mid-hero: spinning up from
    // nothing when the visitor is already past it would look like a glitch.
    const wantsIntro =
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches &&
      (progress.current ?? 0) < 0.02
    const introStart = wantsIntro ? performance.now() : null

    /** Nearest already-loaded frame at or before `i`, walking backwards around
     *  the loop. Lets the car appear and scrub from the first frame that
     *  arrives instead of waiting for all sixty. */
    const nearestLoaded = (i: number) => {
      for (let k = 0; k < FRAMES; k++) {
        const img = images[(i - k + FRAMES) % FRAMES]
        if (img) return img
      }
      return null
    }

    let pending = 0

    const paint = (progressAtPaint: number) => {
      raf = 0
      const w = cssW
      const h = cssH
      if (!w || !h) return

      const p = clamp01(progressAtPaint)

      // Load-in spin, eased in and out, landing exactly on FRONT.
      const elapsed = introStart == null ? Infinity : performance.now() - introStart
      const introT = introStart == null ? 1 : clamp01(elapsed / INTRO_MS)
      const unveilT =
        introStart == null ? 1 : clamp01((elapsed - UNVEIL_DELAY) / UNVEIL_MS)
      const introOffset = (easeOut(introT) - 1) * INTRO_TURNS * FRAMES

      // Then scroll turns it from FRONT to PROFILE and drives it away.
      let spin = 0
      let dx = 0
      let alpha = 1
      let speed = 0

      if (p <= SPIN_END) {
        spin = easeOut(p / SPIN_END) * (PROFILE - FRONT)
      } else {
        const q = clamp01((p - SPIN_END) / (1 - SPIN_END))
        // Keeps turning on the way out — linear, so the extra rotation is
        // actually visible before the car clears the frame.
        spin = PROFILE - FRONT + q * EXIT_TURNS * FRAMES
        speed = q
        dx = DEPART_DIR * q * q * w * 1.45 // squared: pulls away, never glides
        alpha = 1 - clamp01((q - 0.62) / 0.38)
      }

      const index =
        ((Math.round(FRONT + introOffset + spin) % FRAMES) + FRAMES) % FRAMES

      const img = nearestLoaded(index)
      if (!img) return

      const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight)
      const dw = img.naturalWidth * scale
      const dh = img.naturalHeight * scale
      const x = (w - dw) / 2 + dx
      const y = (h - dh) / 2

      ctx.clearRect(0, 0, w, h)

      // A short smear behind it once it is actually moving, so the departure
      // reads as speed rather than the image sliding sideways.
      if (speed > 0.12) {
        const smear = -DEPART_DIR * speed * dw * 0.09
        for (let g = 2; g >= 1; g--) {
          ctx.globalAlpha = alpha * 0.14 * (3 - g)
          ctx.drawImage(img, x + smear * g, y, dw, dh)
        }
      }

      ctx.globalAlpha = alpha
      ctx.drawImage(img, x, y, dw, dh)
      ctx.globalAlpha = 1

      // Unveil. `source-atop` paints only where the car already is, so the
      // shade lands on the model and never on the grid behind it — the
      // silhouette stays readable at 0.9 alpha rather than going fully black.
      if (unveilT < 1) {
        const lit = easeOut(unveilT)
        const feather = dh * 0.3
        const front = y + dh + feather - lit * (dh + feather * 2)

        ctx.globalCompositeOperation = 'source-atop'

        const shade = ctx.createLinearGradient(0, front - feather, 0, front)
        shade.addColorStop(0, 'rgba(5, 6, 8, 0.78)')
        shade.addColorStop(1, 'rgba(5, 6, 8, 0)')
        ctx.fillStyle = shade
        ctx.fillRect(0, 0, w, h)

        // A warm band riding the light front, so it reads as a light being
        // raised over the car rather than a mask sliding off it.
        const edge = ctx.createLinearGradient(0, front - feather * 0.45, 0, front + feather * 0.2)
        edge.addColorStop(0, 'rgba(255, 138, 61, 0)')
        edge.addColorStop(0.5, 'rgba(255, 156, 88, 0.3)')
        edge.addColorStop(1, 'rgba(255, 138, 61, 0)')
        ctx.fillStyle = edge
        ctx.fillRect(0, 0, w, h)

        ctx.globalCompositeOperation = 'source-over'
      }
    }

    const schedule = (p: number) => {
      pending = p
      if (!raf && !stopped) raf = requestAnimationFrame(() => paint(pending))
    }
    const repaint = () => schedule(progress.current ?? 0)

    const resize = () => {
      const w = wrap.clientWidth
      const h = wrap.clientHeight
      if (!w || !h || (w === cssW && h === cssH)) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      cssW = w
      cssH = h
      canvas.width = Math.round(w * dpr)
      canvas.height = Math.round(h * dpr)
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      repaint()
    }

    // Frame 0 first so something is on screen as early as possible, then the
    // rest; the browser's own connection pool handles the queueing.
    const load = (i: number) => {
      const img = new Image()
      img.decoding = 'async'
      img.onload = () => {
        images[i] = img
        repaint()
      }
      img.src = frameSrc(i)
    }

    load(0)
    for (let i = 1; i < FRAMES; i++) load(i)

    // A ResizeObserver, not a window resize listener. Measuring once on mount
    // is not safe: WebKit had not finished laying the stage out at that point
    // and reported a 158px-tall box, which then stuck forever because no window
    // resize ever followed. This tracks the element itself, so late layout,
    // font loading and viewport changes all correct themselves.
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)
    resize()

    // Progress is pushed in, not polled off a scroll event of our own — see the
    // note in useHeroScroll about child effects running first.
    const unsubscribe = subscribe(schedule)

    // The load-in is time-based, so it needs its own loop until it settles.
    // After that every repaint is driven by scroll.
    if (introStart != null) {
      const introLoop = () => {
        if (stopped) return
        paint(progress.current ?? 0)
        introRaf =
          performance.now() - introStart < UNVEIL_DELAY + UNVEIL_MS
            ? requestAnimationFrame(introLoop)
            : 0
      }
      introRaf = requestAnimationFrame(introLoop)
    }

    return () => {
      stopped = true
      if (raf) cancelAnimationFrame(raf)
      if (introRaf) cancelAnimationFrame(introRaf)
      ro.disconnect()
      unsubscribe()
    }
  }, [progress, subscribe])

  return (
    <div className="hero-car" ref={wrapRef} aria-hidden="true">
      <canvas ref={canvasRef} />
    </div>
  )
}
