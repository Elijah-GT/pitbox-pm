import { useState } from 'react'
import { Link } from 'react-router-dom'

import { AuthShell, NotWiredNotice } from '../components/AuthShell'

export function Signup() {
  const [submitted, setSubmitted] = useState(false)

  return (
    <AuthShell
      title="Create an account"
      subtitle="For the shop, the subteam leads, and next year's team."
      footer={
        <>
          Already have one? <Link to="/login">Log in</Link>
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
          <span>Name</span>
          <input className="input" type="text" name="name" autoComplete="name" required />
        </label>

        <label className="field">
          <span>Email</span>
          <input className="input" type="email" name="email" autoComplete="email" required />
        </label>

        <label className="field">
          <span>Subteam</span>
          <select className="input" name="subteam" defaultValue="">
            <option value="" disabled>
              Pick one…
            </option>
            {['Frame & Chassis', 'Suspension', 'Drivetrain', 'Electrical', 'Business'].map(
              (s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ),
            )}
          </select>
        </label>

        <label className="field">
          <span>Password</span>
          <input
            className="input"
            type="password"
            name="password"
            autoComplete="new-password"
            minLength={8}
            required
          />
          <small className="hint">At least 8 characters.</small>
        </label>

        <button type="submit" className="btn btn-primary btn-lg btn-block">
          Create account
        </button>

        {submitted && <NotWiredNotice />}
      </form>
    </AuthShell>
  )
}
