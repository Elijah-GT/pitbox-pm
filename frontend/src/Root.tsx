import { BrowserRouter, Route, Routes } from 'react-router-dom'

import App from './App'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'
import { NotFound } from './pages/NotFound'
import { Signup } from './pages/Signup'

/**
 * Routing lives here rather than in main.tsx so App.tsx stays what it was: the
 * tracker, and nothing else. It knows nothing about routes.
 *
 * These paths are also declared server-side — app/main.py serves index.html for
 * any non-API path. Adding a route here needs no server change; removing the
 * catch-all there breaks every one of them on refresh.
 */
export function Root() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        {/* .app-shell carries the fixed-viewport sizing the tracker needs; the
            marketing pages scroll normally. See the note in styles.css. */}
        <Route
          path="/app"
          element={
            <div className="app-shell">
              <App />
            </div>
          }
        />
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  )
}
