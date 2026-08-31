import { Link } from 'react-router-dom'

import { SiteFooter } from '../components/SiteFooter'
import { SiteNav } from '../components/SiteNav'

export function NotFound() {
  return (
    <div className="site">
      <SiteNav />
      <main className="section narrow center">
        <p className="eyebrow">404</p>
        <h1 className="section-title">That page came off on the last lap.</h1>
        <p className="muted">Nothing is routed at this address.</p>
        <div className="hero-cta center-cta">
          <Link to="/" className="btn btn-primary btn-lg">
            Back to the start
          </Link>
          <Link to="/app" className="btn btn-ghost btn-lg">
            Open the tracker
          </Link>
        </div>
      </main>
      <SiteFooter />
    </div>
  )
}
