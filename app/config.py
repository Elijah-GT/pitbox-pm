"""Configuration. Every value has a working default so `uvicorn app.main:app` runs
with no setup at all; override any of them in a .env file (see .env.example)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PITBOX_", env_file=".env", extra="ignore")

    team_name: str = "MESA ARC Racing"

    # sqlite:///./pitbox.db for a laptop or a small shop server.
    # postgresql+psycopg://user:pass@host/db when you outgrow it — nothing else changes.
    database_url: str = "sqlite:///./pitbox.db"

    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 100

    # --- who is allowed in ---------------------------------------------------
    # cloudflare : Cloudflare Access decides. The app verifies the JWT that
    #              Cloudflare signs, then creates a member record the first time
    #              it sees someone. No passwords, no accounts to create, nothing
    #              to hand over but the dashboard login.
    # password   : the built-in login (scrypt + sessions). For running without
    #              Cloudflare -- a shop PC, a campus VM behind a VPN.
    # none       : wide open. Local development only.
    #
    # Defaults to cloudflare so a careless deploy fails closed rather than open.
    # dev.ps1 sets `none` explicitly, because that is what it is for.
    auth_mode: Literal["cloudflare", "password", "none"] = "cloudflare"

    # --- Cloudflare Access ---------------------------------------------------
    # Both of these are REQUIRED in cloudflare mode; the app refuses to start
    # without them rather than falling back to trusting a header.
    #
    # Your Zero Trust team domain. `yourteam` is expanded to
    # `yourteam.cloudflareaccess.com`, and a full URL is accepted too.
    access_team_domain: str = ""

    # The Application Audience (AUD) tag, from the Access application's Overview
    # tab. This is what ties a token to THIS app: without it, a token minted for
    # any other application on your Cloudflare team would be accepted here.
    access_aud: str = ""

    # Cloudflare signs a JWT and puts it here. Unlike the email header, this
    # cannot be forged by anyone who can reach the app -- which is what makes it
    # safe on a host with a public URL, such as Fly.io.
    access_jwt_header: str = "Cf-Access-Jwt-Assertion"

    # How long to cache Cloudflare's public keys. They rotate about every six
    # weeks; an unknown key id triggers an immediate refresh regardless.
    access_jwks_ttl_seconds: int = 3600

    # --- host allowlist ------------------------------------------------------
    # Comma-separated hostnames that may be used to reach the app; empty means
    # any. Set it to your real hostname on a host that also gives you a public
    # URL you did not ask for (fly.dev, onrender.com), so that URL is refused
    # before a request touches anything. Defence in depth: JWT verification is
    # what actually stops a forged identity.
    allowed_hosts: str = ""

    session_days: int = 30

    # Set PITBOX_COOKIE_SECURE=true once you are behind HTTPS, so the session
    # cookie is never sent over a plain connection. Left false by default
    # because on http://localhost a secure cookie is simply dropped, and a login
    # that silently fails to stick is a miserable thing to debug.
    cookie_secure: bool = False

    # Extensions we refuse outright. Everything else is allowed but is always
    # served back as an attachment, never executed or inlined.
    blocked_extensions: tuple[str, ...] = (
        ".exe", ".dll", ".bat", ".cmd", ".com", ".scr", ".msi", ".ps1", ".sh", ".jar",
    )

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
