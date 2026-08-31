import { Link } from 'react-router-dom'

import { useFooterReveal } from '../hooks/useFooterReveal'
import { Wordmark } from './Wordmark'

/**
 * Four link columns under a newsletter block, with a monospace legal bar —
 * GitHub's footer shape. The trademark note stays: it was accurate before and
 * a bigger footer does not make it less necessary.
 */
const COLUMNS = [
  {
    title: 'The tool',
    links: [
      { label: 'What is Baja?', href: '/#what' },
      { label: 'Competition', href: '/#competition' },
      { label: 'The tracker', href: '/#tool' },
      { label: 'Open the demo', to: '/app' },
    ],
  },
  {
    title: 'The car',
    links: [
      { label: 'Chassis', href: '/#tool' },
      { label: 'Drivetrain', href: '/#tool' },
      { label: 'Suspension', href: '/#tool' },
      { label: 'Electrical', href: '/#tool' },
    ],
  },
  {
    title: 'Team',
    links: [
      { label: 'Log in', to: '/login' },
      { label: 'Request access', to: '/signup' },
      { label: 'API docs', href: '/docs' },
    ],
  },
  {
    title: 'Organization',
    links: [
      { label: 'MESA ARC Racing', href: '/#tool' },
      { label: 'SAE International', href: 'https://www.sae.org/' },
    ],
  },
]

export function SiteFooter({ reveal = false }: { reveal?: boolean } = {}) {
  // Only the landing page runs the under-page reveal; everywhere else the
  // footer is an ordinary block at the end of the document.
  const ref = useFooterReveal<HTMLElement>()
  return (
    <footer className={reveal ? 'site-footer footer-reveal' : 'site-footer'} ref={reveal ? ref : undefined}>
      <div className="site-footer-inner" style={{ display: 'block' }}>
        <div className="foot-news">
          <Link to="/" className="site-brand" style={{ marginBottom: 18 }}>
            <span className="brand-inner">
              <Wordmark />
            </span>
          </Link>
          <p className="foot-kicker">Part tracking for Baja SAE</p>
          <p className="muted" style={{ marginTop: 12, maxWidth: '46ch' }}>
            The team's own part tracker for Baja SAE. Access is by invite.
          </p>
          <Link to="/signup" className="btn btn-primary" style={{ marginTop: 18 }}>
            Request access
          </Link>
        </div>

        <div className="foot-cols">
          {COLUMNS.map((col) => (
            <div className="foot-col" key={col.title}>
              <h4>{col.title}</h4>
              <ul>
                {col.links.map((l) => (
                  <li key={l.label}>
                    {l.to ? (
                      <Link to={l.to}>{l.label}</Link>
                    ) : (
                      <a href={l.href}>{l.label}</a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="foot-legal">
          <span>© {new Date().getFullYear()} MESA ARC Racing</span>
          <span>Internal tool</span>
          <span>Access by invite</span>
        </div>

        <p className="foot-note">
          Baja SAE® is a registered trademark of SAE International. This is a student
          team's own tool and is not affiliated with or endorsed by SAE International.
        </p>
      </div>
    </footer>
  )
}
