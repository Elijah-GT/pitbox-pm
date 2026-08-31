import { useState } from 'react'
import { Link } from 'react-router-dom'

import { AuthShell, NotWiredNotice } from '../components/AuthShell'

export function Login() {
  const [submitted, setSubmitted] = useState(false)

  return (
    <AuthShell
      title="Log in"
      subtitle="Pick up where the team left off."
      footer={
        <>
          No account yet? <Link to="/signup">Create one</Link>
        </>
      }
    >
      <form
        className="auth-form"
        onSubmit={(e) => {
          e.preventDefault()
          setSubmitted(true)
        }}
      >
        <label className="field">
          <span>Email</span>
          <input className="input" type="email" name="email" autoComplete="email" required />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            className="input"
            type="password"
            name="password"
            autoComplete="current-password"
            required
          />
        </label>

        <button type="submit" className="btn btn-primary btn-lg btn-block">
          Log in
        </button>

        {submitted && <NotWiredNotice />}
      </form>
    </AuthShell>
  )
}
