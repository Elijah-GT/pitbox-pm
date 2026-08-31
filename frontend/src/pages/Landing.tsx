import { useRef, useState } from 'react'
import { Suspense, lazy } from 'react'
import { Link, useNavigate } from 'react-router-dom'

/* three.js is ~950 KB. Lazy so it never sits in the critical path — the
   wordmark paints first and the car arrives when it is ready. */
const HeroCar3D = lazy(() =>
  import('../components/HeroCar3D').then((m) => ({ default: m.HeroCar3D })),
)


import { LifeField } from '../components/LifeField'
import { Starfield } from '../components/Starfield'
import { SiteFooter } from '../components/SiteFooter'
import { SiteNav } from '../components/SiteNav'
import { useHeroScroll } from '../hooks/useHeroScroll'
import { useReveal } from '../hooks/useReveal'

/** Static events are judged; dynamic events are driven. */
/**
 * A visual slot in a bezel. Pass `src` and it renders the screenshot; leave it
 * off and it renders a labelled placeholder at the same aspect ratio, so the
 * layout is already final and dropping a real image in later changes one line
 * and shifts nothing.
 */
function ShotSlot({
  src,
  alt = '',
  label,
  hint,
}: {
  src?: string
  alt?: string
  label: string
  hint?: string
}) {
  if (src) return <img className="shot" src={src} alt={alt} loading="lazy" />
  return (
    <div className="shot shot-empty" role="img" aria-label={`Placeholder — ${label}`}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
        <rect x="3" y="4.5" width="18" height="15" rx="2.5" />
        <circle cx="8.5" cy="10" r="1.6" />
        <path d="M4 17l4.5-4.5 3.5 3.5 3-2.5L20 18" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="shot-label">{label}</span>
      {hint ? <span className="shot-hint">{hint}</span> : null}
    </div>
  )
}

/** GitHub's repeated unit: glyph, centred headline, centred sub, then a visual. */
/**
 * GitHub leads with a field, not a button. It carries the address to /signup so
 * nothing is silently swallowed — the account still gets created there, behind
 * the invite code.
 */
function EmailCapture() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  return (
    <form
      className="emailcap-row"
      onSubmit={(e) => {
        e.preventDefault()
        navigate(`/signup?email=${encodeURIComponent(email)}`)
      }}
    >
      <div className="emailcap">
        <input
          type="email"
          required
          placeholder="you@school.edu"
          aria-label="Email address"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button type="submit" className="btn btn-primary">
          Request access
        </button>
      </div>
      <Link to="/app" className="btn btn-ghost btn-lg">
        Try the demo tree
      </Link>
    </form>
  )
}

export function Landing() {
  const { sectionRef, stageRef, progressRef, subscribe } = useHeroScroll()
  const whatRef = useRef<HTMLElement>(null)
  // Staggered, so the card arrives and then fills in rather than everything
  // landing at once. The delays only apply on the observer path; the native
  // path staggers with animation-range instead.
  const ctaRef = useReveal<HTMLDivElement>(0)
  const cardRef = useReveal<HTMLDivElement>(90)
  const headRef = useReveal<HTMLHeadingElement>(190)
  const subRef = useReveal<HTMLParagraphElement>(270)

  return (
    <div className="site">
      <SiteNav />

      <main>
        {/* ===== Hero ===== */}
        {/* Nothing but the grid, the name and the car. The stage is pinned, so
            scrolling here dissolves the wordmark without moving the page. */}
        <section className="hero" ref={sectionRef}>
          <div className="hero-stage" ref={stageRef}>
            <div
              className="hero-bg"
              style={{ contain: 'layout style paint' }}
              aria-hidden="true"
            >
              <LifeField className="hero-life" />
              {/* <div className="hero-grids">
                <span className="grid-a" />
                <span className="grid-b" />
              </div> */}
              <div className="hero-mask" />
              <div className="hero-bottom" />
            </div>

            <h1 className="hero-mark">
              <span className="hero-mark-in">
                <span className="hm-thin">Pit</span> <span className="hm-bold">Box</span>
              </span>
            </h1>

            <Suspense fallback={null}>
              <HeroCar3D progress={progressRef} subscribe={subscribe} />
            </Suspense>

            <div className="hero-card">
              <ShotSlot
                src="/shots/tracker.webp"
                label="The tracker"
                alt="The Pit Box tracker: the Baja 2026 Car part tree with Front Upright, LH selected, showing its part number, status, assignee, material, mass and unit cost alongside the breakdown by material."
              />
            </div>

            {/* The header's actions live here first, under the car. The nav
                only takes over once these have scrolled out of sight. */}
            <div className="hero-cta">
              <Link to="/login" className="btn btn-ghost">
                Log in
              </Link>
              <Link to="/signup" className="btn btn-primary">
                Sign up
              </Link>
            </div>

            <div className="hero-cue" aria-hidden="true">
              <span>Scroll</span>
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M8 3 v9 M4 8.5 l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
        </section>

        {/* ===== What is Baja SAE — the page's one content block =====
            Each piece carries its own reveal rather than one on the section.
            A single observer plus descendant rules would strand the children at
            opacity 0 in browsers that take the native scroll-timeline path,
            where `is-in` is never added. */}
        <section id="what" className="gh-section" ref={whatRef}>
          {/* The ask sits above the card, not inside it. */}
          <div className="section-cta reveal r1" ref={ctaRef}>
            <EmailCapture />
          </div>

          <div className="gh-stage">
            <Starfield className="glow-stars" />
            <div className="bezel reveal r2" ref={cardRef}>
              <div className="bezel-pad bezel-head">
                <h2 className="gh-h reveal r3" ref={headRef}>
                  Built and raced by students, judged by engineers
                </h2>
                <p className="gh-sub reveal r4" ref={subRef}>
                  An intercollegiate competition run by SAE International, part of its
                  Collegiate Design Series.
                </p>
              </div>
            </div>
          </div>
        </section>

      </main>

      {/* The spacer is what gives the fixed footer room to be uncovered. */}
      <div className="foot-spacer" aria-hidden="true" />
      <SiteFooter reveal />
    </div>
  )
}
