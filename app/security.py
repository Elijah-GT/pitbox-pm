"""Passwords, sessions, and the dependency that guards every API route.

PASSWORD HASHING
----------------
Uses scrypt from Python's own hashlib -- no new dependency. scrypt is a
memory-hard KDF, so it resists GPU cracking in a way a plain SHA never can.
The cost parameters are stored alongside each hash, so they can be raised in a
few years without invalidating anyone's existing password.

Deliberately NOT bcrypt/passlib: that is two more packages to keep alive for a
team that hands this over every year, and passlib in particular has a history
of breaking against new bcrypt releases.

SESSIONS
--------
Server-side, in the sessions table. A signed stateless cookie would avoid the
lookup, but could not be revoked -- and "this person graduated, cut their
access now" is a thing that actually happens here. Only the hash of the token
is stored; the token itself lives solely in the user's cookie.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .access_jwt import (
    AccessConfigError,
    AccessKeysUnavailable,
    InvalidAccessToken,
    get_verifier,
)
from .config import settings
from .database import get_db
from .models import Member, Session, utcnow

COOKIE_NAME = "pitbox_session"

# Cloudflare sets this on the browser after a successful Access login. It holds
# the same signed token as the Cf-Access-Jwt-Assertion header.
ACCESS_COOKIE_NAME = "CF_Authorization"

# scrypt cost. n=2**14 with r=8 needs 128*n*r = 16 MB and takes ~100 ms, which
# is the usual interactive-login target: unnoticeable to a person, punishing to
# anyone working through a leaked password list.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024


# --- password hashing --------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN, maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Returns False for members who have no password set."""
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(key_hex) // 2, maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        # A malformed hash must fail closed, never raise into the request.
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(key_hex))


# --- brute-force throttle ----------------------------------------------------
# Deliberately simple: an in-process counter, so it resets on restart and does
# not span multiple workers. scrypt already makes guessing expensive; this just
# stops someone hammering one account from a script. If you ever run more than
# one worker, move this to the database or put a rate limit at the proxy.

_FAILS: dict[str, tuple[int, float]] = {}
_MAX_FAILS = 8
_LOCKOUT_SECONDS = 300


def throttle_check(key: str) -> int:
    """Seconds the caller must wait, or 0 if they may try now."""
    count, until = _FAILS.get(key, (0, 0.0))
    if count >= _MAX_FAILS and time.monotonic() < until:
        return int(until - time.monotonic()) + 1
    return 0


def throttle_fail(key: str) -> None:
    count, _ = _FAILS.get(key, (0, 0.0))
    count += 1
    _FAILS[key] = (count, time.monotonic() + _LOCKOUT_SECONDS)


def throttle_reset(key: str) -> None:
    _FAILS.pop(key, None)


# --- sessions ----------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: DbSession, member: Member, user_agent: str | None = None) -> str:
    """Start a session and return the raw token to put in the cookie."""
    token = secrets.token_urlsafe(32)
    db.add(Session(
        token_hash=_hash_token(token),
        member_id=member.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_days),
        user_agent=(user_agent or "")[:300] or None,
    ))
    member.last_login_at = utcnow()
    db.commit()
    return token


def destroy_session(db: DbSession, token: str) -> None:
    row = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if row is not None:
        db.delete(row)
        db.commit()


def purge_expired_sessions(db: DbSession) -> int:
    now = datetime.now(timezone.utc)
    stale = list(db.scalars(select(Session).where(Session.expires_at < now)))
    for row in stale:
        db.delete(row)
    if stale:
        db.commit()
    return len(stale)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=settings.session_days * 24 * 3600,
        httponly=True,          # JavaScript cannot read it, so XSS cannot steal it
        samesite="lax",         # blocks cross-site POST/PATCH/DELETE, i.e. CSRF
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# --- request dependencies ----------------------------------------------------

def upsert_access_member(db: DbSession, email: str) -> Member:
    """Find or create the member for a Cloudflare-verified email address.

    Members appear on first sight, which is the point of this mode: a new
    teammate with a school email signs in and is simply there, in the assignee
    list too, with nobody creating an account for them.
    """
    email = email.strip().lower()
    member = db.scalar(select(Member).where(func.lower(Member.email) == email))
    if member is None:
        # Name it after the local part until they edit it -- "e.carter" beats
        # a blank row, and they can fix it in the app.
        member = Member(name=email.split("@")[0].replace(".", " ").title(), email=email)
        db.add(member)
        db.commit()
        db.refresh(member)
    elif not member.is_active:
        # Deactivated locally but still allowed by the Access policy. Access is
        # the authority in this mode, so let them back in.
        member.is_active = True
        db.commit()

    member.last_login_at = utcnow()
    db.commit()
    return member


def member_from_access_jwt(request: Request, db: DbSession) -> Member | None:
    """Identity proved by Cloudflare's signature, not by a header we hope is real.

    The `Cf-Access-Authenticated-User-Email` header is deliberately ignored.
    Trusting it is only safe when nothing but the tunnel can reach the app, and
    that stops being true the moment this is deployed somewhere with its own
    public hostname -- Fly.io hands out a *.fly.dev URL whether you want one or
    not. A signature holds up either way, so that is what gets checked.

    See app/access_jwt.py for what is verified, and docs/CLOUDFLARE.md for the
    two settings this needs.
    """
    token = (
        request.headers.get(settings.access_jwt_header)
        # Browsers navigating directly carry the same token as a cookie. Reading
        # it too means /api/health-style links and plain page loads behave the
        # same as XHR, with no separate code path to get wrong.
        or request.cookies.get(ACCESS_COOKIE_NAME)
    )
    if not token:
        return None

    try:
        email = get_verifier().email_from(token)
    except AccessConfigError as exc:
        # Startup should have caught this, so reaching here means the settings
        # were changed underneath a running process.
        raise HTTPException(500, str(exc)) from exc
    except AccessKeysUnavailable as exc:
        # Our problem, not the caller's: say so with a 5xx so a monitor pages
        # someone instead of a member being told they are not allowed in.
        raise HTTPException(503, f"Cannot reach Cloudflare to verify sign-in. {exc}") from exc
    except InvalidAccessToken as exc:
        raise HTTPException(403, f"Cloudflare Access token rejected: it {exc}") from exc

    return upsert_access_member(db, email)


def current_member_optional(request: Request, db: DbSession = Depends(get_db)) -> Member | None:
    """Resolve who is making this request, according to the configured mode."""
    if settings.auth_mode == "none":
        return _local_dev_member(db)

    if settings.auth_mode == "cloudflare":
        return member_from_access_jwt(request, db)

    # password mode: the built-in session cookie
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    row = db.scalar(select(Session).where(Session.token_hash == _hash_token(token)))
    if row is None:
        return None

    # SQLite hands back naive datetimes even for timezone=True columns, so
    # compare in UTC explicitly rather than trusting tzinfo to be present.
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None

    member = db.get(Member, row.member_id)
    # Deactivating someone cuts their access on their very next request.
    if member is None or not member.is_active:
        return None
    return member


_DEV_EMAIL = "local@localhost"


def _local_dev_member(db: DbSession) -> Member:
    """auth_mode=none: everyone is the same local user.

    Exists so the app is usable offline with no login at all. Never reachable in
    the other modes, and main.py logs a warning at startup when this is on.
    """
    member = db.scalar(select(Member).where(Member.email == _DEV_EMAIL))
    if member is None:
        member = Member(name="Local User", email=_DEV_EMAIL, is_admin=True)
        db.add(member)
        db.commit()
        db.refresh(member)
    return member


def require_member(member: Member | None = Depends(current_member_optional)) -> Member:
    if member is not None:
        return member
    if settings.auth_mode == "cloudflare":
        # Almost always a misconfiguration rather than a signed-out user: the
        # hostname was reached without going through Cloudflare, or no Access
        # application is attached to it. A forged email header lands here too,
        # which is the entire point.
        raise HTTPException(
            403,
            "No verified Cloudflare Access token on this request. Reach this app "
            "through the hostname your Access application protects, not through "
            "its origin URL. For local use, set PITBOX_AUTH_MODE=none.",
        )
    raise HTTPException(401, "Not signed in.")


def require_admin(member: Member = Depends(require_member)) -> Member:
    """Roster management.

    Only meaningful in password mode. Under Cloudflare Access the gate is the
    Access policy itself -- everyone who got this far was allowed in by it, and
    there is no admin flag to grant because there are no accounts to manage.
    Enforcing it here would just lock everyone out of the roster screen.
    """
    if settings.auth_mode != "password":
        return member
    if not member.is_admin:
        raise HTTPException(403, "That action needs an admin account.")
    return member
