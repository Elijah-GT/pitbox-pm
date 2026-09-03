"""Sign in, sign out, and the login page.

The login page is served by the backend rather than built into either frontend.
Both UIs get authentication from one implementation, and an expired session can
redirect anywhere to a page that is guaranteed to exist.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import schemas, security
from ..config import settings
from ..database import get_db
from ..models import Member


def _require_password_mode() -> None:
    """The built-in login is off unless PITBOX_AUTH_MODE=password."""
    if settings.auth_mode != "password":
        raise HTTPException(
            404,
            f"The built-in login is disabled (auth_mode={settings.auth_mode}). "
            "Access is handled by Cloudflare Access.",
        )

router = APIRouter(tags=["auth"])


@router.post("/api/auth/login", response_model=schemas.MemberOut)
def login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
):
    _require_password_mode()
    email = payload.email.strip().lower()

    wait = security.throttle_check(email)
    if wait:
        raise HTTPException(429, f"Too many failed attempts. Try again in {wait} seconds.")

    member = db.scalar(select(Member).where(func.lower(Member.email) == email))

    # One message for "no such account", "wrong password" and "deactivated", so
    # the form cannot be used to discover who has an account here.
    if member is None or not member.is_active or not security.verify_password(
        payload.password, member.password_hash
    ):
        security.throttle_fail(email)
        raise HTTPException(401, "Wrong email or password.")

    security.throttle_reset(email)
    token = security.create_session(db, member, request.headers.get("user-agent"))
    security.set_session_cookie(response, token)
    return member


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: DbSession = Depends(get_db)):
    _require_password_mode()
    token = request.cookies.get(security.COOKIE_NAME)
    if token:
        security.destroy_session(db, token)
    security.clear_session_cookie(response)


@router.get("/api/auth/me", response_model=schemas.MemberOut)
def me(member: Member = Depends(security.require_member)):
    return member


@router.patch("/api/auth/me", response_model=schemas.MemberOut)
def update_own_profile(
    payload: schemas.ProfileUpdate,
    db: DbSession = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    """Set your own display name.

    Self-service on purpose, with no admin check: under Cloudflare Access a new
    member is created from their email address, which at a lot of schools is an
    ID like W1234567. Nobody can tell who that is on an assignee dropdown, and
    making an admin fix it by hand is exactly the sort of chore this app is
    meant not to have.

    Only name and subteam. Email is the identity Cloudflare verified, so it is
    not editable here -- changing it would let someone become a teammate on
    their next request.
    """
    member.name = payload.name.strip()
    if payload.subteam is not None:
        member.subteam = payload.subteam.strip() or None
    member.name_confirmed = True
    db.commit()
    db.refresh(member)
    return member


@router.post("/api/auth/password", status_code=204)
def change_own_password(
    payload: schemas.PasswordChange,
    request: Request,
    db: DbSession = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    """Change your own password.

    Requires the current one, so someone who walks up to an unlocked laptop
    cannot lock the real owner out. Every OTHER session is dropped, on the
    assumption that a password change may be a response to one being stolen —
    the browser doing the changing stays signed in.
    """
    _require_password_mode()
    if not security.verify_password(payload.current_password, member.password_hash):
        raise HTTPException(401, "Current password is wrong.")

    member.password_hash = security.hash_password(payload.new_password)

    keep = request.cookies.get(security.COOKIE_NAME)
    keep_hash = security._hash_token(keep) if keep else None
    from ..models import Session as SessionRow  # local import avoids a cycle at module load
    for row in db.scalars(select(SessionRow).where(SessionRow.member_id == member.id)):
        if row.token_hash != keep_hash:
            db.delete(row)
    db.commit()


@router.get("/login", include_in_schema=False, response_class=HTMLResponse)
def login_page(member: Member | None = Depends(security.current_member_optional)):
    _require_password_mode()
    if member is not None:
        # Already signed in — don't make them look at a login form.
        return HTMLResponse('<meta http-equiv="refresh" content="0; url=/">', status_code=200)
    return HTMLResponse(LOGIN_HTML.replace("{{TEAM}}", settings.team_name))


# Self-contained on purpose: no bundle, no framework, works whether or not the
# React app has ever been built.
#
# RAW string. The inline JS contains regex escapes (\/ and \\); in a normal
# string Python would eat them and ship a broken character class to the browser.
LOGIN_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Sign in — CarHub</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128295;</text></svg>" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
<style>
  :root{--bg:#0e0f12;--surface:#1c1f26;--border:#2a2e37;--text:#f2f3f5;
        --dim:#aab0bc;--muted:#767d8c;--accent:#ff6a1a;--danger:#ef4444;color-scheme:dark}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;
       min-height:100vh;display:grid;place-items:center;padding:24px}
  .card{width:100%;max-width:370px}
  .brand{display:flex;align-items:center;gap:9px;justify-content:center;margin-bottom:26px;
         font-family:Oswald,sans-serif;font-size:1.5rem;font-weight:700;
         text-transform:uppercase;letter-spacing:.6px;color:var(--accent)}
  .brand em{font-style:normal;color:var(--text)}
  .team{text-align:center;color:var(--muted);font-size:.8rem;margin-top:-20px;margin-bottom:26px}
  form{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:22px}
  label{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.6px;
        color:var(--muted);margin-bottom:5px}
  input{width:100%;background:#14161b;border:1px solid var(--border);border-radius:8px;
        color:var(--text);padding:10px 12px;font:inherit;outline:none;margin-bottom:15px}
  input:focus-visible{border-color:var(--accent);box-shadow:0 0 0 2px rgba(255,106,26,.15)}
  button{width:100%;background:var(--accent);border:0;border-radius:8px;color:#14100c;
         font:inherit;font-weight:600;padding:11px;cursor:pointer}
  button:hover{background:#ffb547}
  button:disabled{opacity:.6;cursor:default}
  .err{background:#3a1f24;border:1px solid #7a3b3b;color:#ffc9c9;border-radius:8px;
       padding:9px 11px;font-size:.85rem;margin-bottom:14px;display:none}
  .foot{text-align:center;color:var(--muted);font-size:.74rem;margin-top:16px;line-height:1.6}
</style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <svg viewBox="0 0 48 48" width="26" height="26" aria-hidden="true">
        <path d="M6 34 L18 12 L26 24 L34 14 L42 34 Z" fill="none" stroke="currentColor"
              stroke-width="3" stroke-linejoin="round"/>
        <circle cx="16" cy="38" r="4" fill="currentColor"/>
        <circle cx="34" cy="38" r="4" fill="currentColor"/>
      </svg>
      <span>Car<em>Hub</em></span>
    </div>
    <p class="team">{{TEAM}}</p>

    <form id="f">
      <div class="err" id="err" role="alert"></div>
      <label for="email">Email</label>
      <input id="email" name="email" type="email" autocomplete="username" required autofocus />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required />
      <button id="go" type="submit">Sign in</button>
    </form>

    <p class="foot">No account? Ask a team lead to create one for you.</p>
  </div>

<script>
const form = document.getElementById('f');
const err  = document.getElementById('err');
const go   = document.getElementById('go');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  err.style.display = 'none';
  go.disabled = true;
  go.textContent = 'Signing in…';
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value,
      }),
    });
    if (res.ok) {
      // ?next= is set by the app when a session expires mid-use.
      // Must be a single-slash local path: '//evil.com' and '/\\evil.com' are
      // protocol-relative URLs and would turn this into an open redirect.
      const next = new URLSearchParams(location.search).get('next');
      location.href = (next && /^\/[^/\\]/.test(next)) ? next : '/';
      return;
    }
    const body = await res.json().catch(() => ({}));
    err.textContent = body.detail || `Sign in failed (${res.status})`;
    err.style.display = 'block';
  } catch {
    err.textContent = 'Could not reach the server. Is the backend running?';
    err.style.display = 'block';
  }
  go.disabled = false;
  go.textContent = 'Sign in';
});
</script>
</body>
</html>
"""
