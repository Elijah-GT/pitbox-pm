import { useState } from 'react'

/**
 * The remaining archetypes from GitHub's landing page, rebuilt: a segmented
 * tablist, a logo marquee, an accordion, stat cells, a pull quote, and the
 * three-up story cards. Their structure and rhythm; our content — anything
 * that would have to be a real customer, logo or quote is a labelled
 * placeholder rather than something invented.
 */

const PHASES = [
  {
    id: 'design',
    label: 'Design',
    body: 'Lay out the car as a tree before a single tube is cut. Subsystems, assemblies, parts — and the decisions behind each one, ready to defend at Design.',
  },
  {
    id: 'build',
    label: 'Build',
    body: 'Track what is designed, ordered, machined, welded and installed. Filter to everything still pending without losing where it sits in the car.',
  },
  {
    id: 'test',
    label: 'Test',
    body: 'Log what broke and what you changed. The bracket that failed in October is still on the part when you rebuild it in February.',
  },
  {
    id: 'compete',
    label: 'Compete',
    body: 'Walk into tech inspection with the bill of materials, the masses and the drawings attached to the parts they describe.',
  },
]

export function PhaseTabs() {
  const [active, setActive] = useState(PHASES[0].id)
  const current = PHASES.find((p) => p.id === active) ?? PHASES[0]
  return (
    <>
      <div className="seg" role="tablist" aria-label="Season phase">
        {PHASES.map((p) => (
          <button
            key={p.id}
            role="tab"
            type="button"
            id={`tab-${p.id}`}
            aria-selected={p.id === active}
            aria-controls="phase-panel"
            onClick={() => setActive(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <p className="seg-panel" role="tabpanel" id="phase-panel" aria-labelledby={`tab-${current.id}`}>
        {current.body}
      </p>
    </>
  )
}

/** Sponsor strip. Real Baja teams run sponsor walls; these are empty slots
 *  until the team drops logos in, never invented brands. */
export function SponsorMarquee() {
  const [paused, setPaused] = useState(false)
  const slots = ['SPONSOR', 'SPONSOR', 'SPONSOR', 'SPONSOR', 'SPONSOR', 'SPONSOR']
  return (
    <div className="marquee" data-paused={paused}>
      <div className="marquee-track">
        {[...slots, ...slots].map((s, i) => (
          <span className="marquee-item" key={i} aria-hidden={i >= slots.length}>
            {s}
          </span>
        ))}
      </div>
      <button
        type="button"
        className="marquee-pause"
        aria-label={paused ? 'Play sponsor marquee' : 'Pause sponsor marquee'}
        onClick={() => setPaused((v) => !v)}
      >
        {paused ? '▶' : '❚❚'}
      </button>
    </div>
  )
}

const FAQ = [
  {
    q: 'Tag a branch, not a hundred parts',
    a: 'Tags cascade down the tree by path, so tagging a subsystem tags everything beneath it — including parts added weeks later. Nothing has to be re-tagged when the car changes shape.',
  },
  {
    q: 'Find every part that shares a problem',
    a: 'Connections link parts across the whole tree by status, vendor, material or tag, so "everything waiting on the same supplier" is one click even when those parts live in four different subsystems.',
  },
  {
    q: 'Files live on the part they describe',
    a: 'Datasheets, CAD, drawings and firmware attach to the node itself and are versioned, so last season’s revision is always recoverable and never lives in someone’s downloads folder.',
  },
  {
    q: 'Built for this team, by this team',
    a: 'Pit Box is our own tool, not a product. It is shaped around how we actually run a season, and access is limited to members of the team by invite.',
  },
]

export function FeatureAccordion() {
  return (
    <div className="acc">
      {FAQ.map((item, i) => (
        <details key={item.q} open={i === 0}>
          <summary>
            {item.q}
            <span className="acc-plus" aria-hidden="true" />
          </summary>
          <p className="acc-body">{item.a}</p>
        </details>
      ))}
    </div>
  )
}

/** Facts about the competition, not invented product metrics. */
const STATS = [
  { n: '4 hours', l: 'of wheel-to-wheel endurance racing to close the competition' },
  { n: '14 hp', l: 'from the Kohler Command Pro CH440 every team in the series runs' },
  { n: '4,000 units', l: 'a year — the production volume the car is designed against' },
]

export function StatRow() {
  return (
    <div className="stats">
      {STATS.map((s) => (
        <div className="stat-cell" key={s.n}>
          <div className="stat-n">{s.n}</div>
          <p className="stat-l">{s.l}</p>
        </div>
      ))}
    </div>
  )
}

/** Deliberately empty: a testimonial has to come from a real person on the
 *  team, so this is a slot with instructions rather than a fabricated quote. */
export function TeamQuote() {
  return (
    <div className="quote-grid">
      <div>
        <p className="gh-sub" style={{ margin: 0, textAlign: 'left' }}>
          Add a line from your team lead once the tracker has a season on it.
        </p>
      </div>
      <div>
        <div className="quote-mark" aria-hidden="true">
          &ldquo;
        </div>
        <blockquote className="q">
          Your quote goes here — what changed for the team once every part had a
          home, a status and an owner.
        </blockquote>
        <div className="q-attr">
          Team member
          <div className="q-role">Role · MESA ARC Racing</div>
        </div>
      </div>
    </div>
  )
}

const STORIES = [
  { logo: 'Drivetrain', label: 'Subsystem', desc: 'CVT, gearbox and axles tracked from concept to installed' },
  { logo: 'Suspension', label: 'Subsystem', desc: 'A-arms, shocks and uprights with mass logged on every part' },
  { logo: 'Chassis', label: 'Subsystem', desc: 'Every tube in the frame, with the drawings attached' },
]

export function SubsystemCards() {
  return (
    <div className="stories">
      {STORIES.map((s, i) => (
        <div className={`story${i === 1 ? ' is-featured' : ''}`} key={s.logo}>
          <div className="story-logo">{s.logo}</div>
          <span className="story-label">{s.label}</span>
          <p className="story-desc">{s.desc}</p>
        </div>
      ))}
    </div>
  )
}
