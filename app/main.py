"""CarHub -- part tracking and project management for a Baja SAE team.

Run it:
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Then open http://127.0.0.1:8000 .
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fastapi import Depends
from fastapi.responses import RedirectResponse

from .access_jwt import get_verifier
from .config import BASE_DIR, settings
from .database import SessionLocal, engine
from .migrate import run_migrations
from .models import Base, Member
from .routers import attachments, auth, members, nodes, projects, tags
from .security import (
    count_admins,
    current_member_optional,
    purge_expired_sessions,
    require_write_access,
    validate_member_writable,
)
from .seed import ensure_default_tags, seed_demo

STATIC_DIR = BASE_DIR / "static"        # the original zero-build UI
VITE_DIST = BASE_DIR / "frontend" / "dist"  # the React build, when present


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # create_all is fine while the schema is still moving and the data is
    # disposable. Once you have a season's worth of real parts in here, switch to
    # Alembic (pip install alembic; alembic init migrations) -- see docs/ARCHITECTURE.md.
    Base.metadata.create_all(bind=engine)
    # create_all builds missing tables but never alters existing ones, so adding
    # the login columns needs this for anyone with a database already.
    run_migrations(engine)
    log = logging.getLogger("pitbox")
    if settings.auth_mode == "none":
        log.warning(
            "PITBOX_AUTH_MODE=none -- there is NO authentication. Fine on a "
            "laptop, never on anything reachable from outside this machine."
        )
    if settings.auth_mode == "cloudflare":
        # Fail loudly at boot rather than per-request. A misconfigured instance
        # that refuses to start is a five-minute fix; one that starts and quietly
        # trusts nobody looks like a network problem for an afternoon.
        # get_verifier() raises AccessConfigError when the two settings are
        # missing, and nothing here falls back to header trust.
        verifier = get_verifier()
        log.info(
            "Cloudflare Access enabled: issuer=%s aud=%s...",
            verifier.issuer, verifier.audience[:8],
        )
    with SessionLocal() as db:
        ensure_default_tags(db)
        seed_demo(db)  # no-op once any project exists
        purge_expired_sessions(db)

        # A database with members but no admin is a locked instance: everyone
        # can read, nobody can change anything, and the Team panel that would
        # fix it is itself admin-only. Deliberately NOT self-healing -- quietly
        # promoting someone would hand the app to whoever opened it next. Say
        # what to run instead.
        if count_admins(db) == 0:
            log.warning(
                "No admin accounts. Everyone can read; nobody can write. "
                "Fix it with:  python scripts/grant_admin.py <email>"
            )
    yield


app = FastAPI(
    title=f"CarHub -- {settings.team_name}",
    description="Hierarchical part tracking for a Baja SAE vehicle.",
    version="0.1.0",
    lifespan=lifespan,
    # The interactive docs are OFF.
    #
    # FastAPI mounts /docs, /redoc and /openapi.json on the app itself rather
    # than on a router, so the `dependencies=[Depends(require_member)]` applied
    # below never touched them: an unauthenticated request got a 403 from
    # /api/projects and a 200 from /openapi.json, complete with every route and
    # request schema. No parts data, but a full map of the API for anyone who
    # found the origin -- and a quiet exception to "protected by default".
    #
    # They were only ever a developer convenience, so they are simply removed.
    # To get them back while working locally, set these to their defaults
    # ("/docs", "/redoc", "/openapi.json") -- but do not ship that.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Refuse hostnames we do not serve, before anything else looks at the request.
# On Fly.io this is what makes the *.fly.dev URL a dead end: the app is reachable
# there, but it answers 400 to everything. Off by default (empty = any host).
if settings.allowed_host_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

# Auth first, and unguarded — you cannot require a session to sign in.
app.include_router(auth.router)

# Everything else requires one, and gates what you may change on who you are.
# Declaring both here rather than on each endpoint means a new route is
# protected by default: you have to go out of your way to expose something,
# instead of remembering to lock it down.
#
# require_write_access depends on require_member, so reads are still gated on
# being signed in. It then splits writes three ways: reads for anyone signed
# in, editing an existing part for any member, and adding/deleting/restructuring
# for admins -- see security.MEMBER_WRITABLE for the exact line and why.
PROTECTED = [projects.router, nodes.router, tags.router, attachments.router, members.router]
for _router in PROTECTED:
    app.include_router(_router, dependencies=[Depends(require_write_access)])

# Import-time, not request-time: if a route in the member allowlist has been
# renamed, this instance refuses to start rather than quietly turning an
# everyday member action into an admin-only one.
validate_member_writable(PROTECTED)


@app.get("/api/health")
def health():
    """Deliberately public, so uptime checks and `fly status` work without a login.
    It reveals only that the service is up and the team name."""
    # auth_mode is here so the UI knows whether to offer a sign-out button and
    # where to point it, and so you can confirm at a glance which mode a running
    # instance is in.
    return {"status": "ok", "team": settings.team_name, "auth_mode": settings.auth_mode}


# The API routes are declared before any static mount so /api/* always wins.
#
# Two frontends can coexist. If the Vite app has been built (npm run build), it
# is served at / and the original no-build UI stays reachable at /static/ as a
# fallback. Nothing here changes when you switch between them.
if VITE_DIST.exists():
    assets = VITE_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index(member: Member | None = Depends(current_member_optional)):  # noqa: ARG001
    # Only password mode has a login page to send people to. Under Cloudflare
    # Access an unidentified request means the tunnel was bypassed, and
    # require_member raises a 403 that explains that.
    if member is None and settings.auth_mode == "password":
        return RedirectResponse("/login", status_code=302)
    if VITE_DIST.exists():
        return FileResponse(VITE_DIST / "index.html")
    if STATIC_DIR.exists():
        return FileResponse(STATIC_DIR / "index.html")
    return {"detail": "No frontend built. Run 'npm run build' in frontend/."}
