"""Cryptographic verification of Cloudflare Access tokens.

WHY THIS EXISTS
---------------
Cloudflare Access proves who you are two different ways, and only one of them
survives being deployed somewhere with a public URL.

  1. It adds a `Cf-Access-Authenticated-User-Email` header. Anyone who can reach
     the app can also send that header. It is trustworthy only when the app is
     literally unreachable except through the tunnel -- a laptop bound to
     127.0.0.1 with no port open.

  2. It adds a `Cf-Access-Jwt-Assertion` header holding a JWT that Cloudflare
     signed with a private key only they hold. Forging one means forging the
     signature, which nobody can do regardless of what they can reach.

On Fly.io (or any host that gives the app its own public hostname) the first
one is worthless: `curl -H 'Cf-Access-Authenticated-User-Email: anyone@x'
https://yourapp.fly.dev/api/projects` walks straight past Access. So this
module verifies the signature instead, and the email header is ignored
entirely.

WHAT GETS CHECKED
-----------------
  * the RS256/ES256 signature, against Cloudflare's published public keys
  * `aud` -- the Application Audience tag of YOUR Access application, so a
    valid token minted for someone else's app on the same team is refused
  * `iss` -- your team's Access domain
  * `exp` / `iat` -- expiry, enforced by PyJWT

All four matter. Checking the signature but not `aud` would let any other
application in your Cloudflare account act as this one.

THE KEYS
--------
Fetched from Cloudflare's certs endpoint and cached. If a refresh fails but we
still hold keys from earlier, the old ones keep being used and a warning is
logged: Cloudflare rotates roughly every six weeks, so slightly stale keys are
overwhelmingly better than refusing everyone because of one flaky DNS lookup.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

import jwt
from jwt import PyJWK

from .config import settings

log = logging.getLogger("pitbox.access")

# Both are asymmetric, so there is no algorithm-confusion risk in allowing the
# pair (the danger is mixing an asymmetric alg with HMAC). Cloudflare signs with
# RS256 today; ES256 is listed so a future rotation does not lock everyone out.
ALGORITHMS = ["RS256", "ES256"]

# Cloudflare rotates keys about every six weeks. An hour is a fine refresh
# interval -- an unknown `kid` forces an immediate refresh anyway.
_MIN_REFRESH_SECONDS = 60


class AccessConfigError(RuntimeError):
    """The app is in cloudflare mode but was never told which team/app to trust."""


class AccessKeysUnavailable(RuntimeError):
    """Cloudflare's public keys could not be fetched and none are cached."""


class InvalidAccessToken(Exception):
    """The token was present but did not verify. Never trust the request."""


def normalize_team_domain(raw: str) -> str:
    """Accept `myteam`, `myteam.cloudflareaccess.com`, or the full URL.

    Getting this wrong is the single most likely setup mistake, and the failure
    it produces (every request refused) looks nothing like its cause, so be
    generous about the shape people paste in.
    """
    domain = raw.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.split("/")[0]
    if not domain:
        return ""
    if "." not in domain:
        domain = f"{domain}.cloudflareaccess.com"
    return domain.lower()


class AccessTokenVerifier:
    """Verifies Access JWTs for one team domain and one application audience."""

    def __init__(self, team_domain: str, audience: str, ttl_seconds: int = 3600,
                 timeout: float = 5.0) -> None:
        self.team_domain = normalize_team_domain(team_domain)
        self.audience = audience.strip()
        if not self.team_domain or not self.audience:
            raise AccessConfigError(
                "PITBOX_AUTH_MODE=cloudflare needs both PITBOX_ACCESS_TEAM_DOMAIN "
                "(e.g. yourteam.cloudflareaccess.com) and PITBOX_ACCESS_AUD (the "
                "Application Audience tag from the Access application's Overview "
                "tab). Without them the app cannot verify Cloudflare's signature, "
                "and it will not fall back to trusting an email header. "
                "See docs/CLOUDFLARE.md."
            )
        self.issuer = f"https://{self.team_domain}"
        self.certs_url = f"{self.issuer}/cdn-cgi/access/certs"
        self.ttl_seconds = ttl_seconds
        self.timeout = timeout

        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._last_attempt = 0.0
        self._lock = threading.Lock()

    # --- key handling --------------------------------------------------------

    def _fetch_keys(self) -> dict[str, PyJWK]:
        req = urllib.request.Request(
            self.certs_url, headers={"User-Agent": "pitbox/1.0"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        keys: dict[str, PyJWK] = {}
        for entry in payload.get("keys", []):
            kid = entry.get("kid")
            if not kid:
                continue
            try:
                keys[kid] = PyJWK.from_dict(entry)
            except Exception:  # noqa: BLE001 - one bad key must not void the set
                log.warning("skipping unusable JWK %s from %s", kid, self.certs_url)
        if not keys:
            raise AccessKeysUnavailable(f"{self.certs_url} returned no usable keys")
        return keys

    def _refresh(self, reason: str) -> None:
        """Best-effort refresh. Keeps the previous keys if the fetch fails."""
        self._last_attempt = time.monotonic()
        try:
            self._keys = self._fetch_keys()
            self._fetched_at = time.monotonic()
            log.info("loaded %d Cloudflare Access keys (%s)", len(self._keys), reason)
        except (urllib.error.URLError, OSError, ValueError, AccessKeysUnavailable) as exc:
            if self._keys:
                log.warning(
                    "could not refresh Cloudflare Access keys (%s); continuing with "
                    "the cached set: %s", reason, exc,
                )
                return
            raise AccessKeysUnavailable(
                f"could not fetch Cloudflare's public keys from {self.certs_url}: {exc}"
            ) from exc

    def _signing_key(self, kid: str | None) -> PyJWK:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > self.ttl_seconds
            if not self._keys or stale:
                self._refresh("startup" if not self._keys else "ttl expired")

            if kid and kid not in self._keys:
                # A key we have never seen usually means Cloudflare rotated.
                # Rate-limited so a stream of tokens carrying junk `kid`s cannot
                # turn into a stream of outbound requests.
                if (time.monotonic() - self._last_attempt) > _MIN_REFRESH_SECONDS:
                    self._refresh(f"unknown kid {kid}")

            if kid is None or kid not in self._keys:
                raise InvalidAccessToken(
                    "signed with a key Cloudflare does not publish for this team "
                    "-- check PITBOX_ACCESS_TEAM_DOMAIN"
                )
            return self._keys[kid]

    # --- verification --------------------------------------------------------

    def verify(self, token: str) -> dict:
        """Return the token's claims, or raise. Never returns unverified data."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidAccessToken(f"not a readable JWT: {exc}") from exc

        key = self._signing_key(header.get("kid"))

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise InvalidAccessToken("expired -- sign in again") from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidAccessToken(
                "issued for a different Access application "
                "-- PITBOX_ACCESS_AUD does not match this hostname's app"
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidAccessToken(
                "issued by a different Cloudflare team "
                "-- check PITBOX_ACCESS_TEAM_DOMAIN"
            ) from exc
        except jwt.PyJWTError as exc:
            raise InvalidAccessToken(str(exc)) from exc

        return claims

    def email_from(self, token: str) -> str:
        claims = self.verify(token)
        email = str(claims.get("email") or "").strip().lower()
        if not email:
            # Service tokens authenticate a machine, not a person: they carry
            # `common_name` and no email, so there is nobody to file work under.
            if claims.get("common_name"):
                raise InvalidAccessToken(
                    "is a service token. Pit Box assigns work to people, so it "
                    "needs a token with an email claim."
                )
            raise InvalidAccessToken("carries no email claim")
        return email


# --- process-wide instance ---------------------------------------------------
# Rebuilt whenever the relevant settings change, so tests can point it at a fake
# issuer without restarting anything.

_verifier: AccessTokenVerifier | None = None
_verifier_key: tuple[str, str] | None = None
_build_lock = threading.Lock()


def get_verifier() -> AccessTokenVerifier:
    """The configured verifier. Raises AccessConfigError if it is not set up."""
    global _verifier, _verifier_key
    wanted = (settings.access_team_domain, settings.access_aud)
    with _build_lock:
        if _verifier is None or _verifier_key != wanted:
            _verifier = AccessTokenVerifier(
                team_domain=wanted[0],
                audience=wanted[1],
                ttl_seconds=settings.access_jwks_ttl_seconds,
            )
            _verifier_key = wanted
        return _verifier


def reset_verifier() -> None:
    """Drop the cached instance. For tests."""
    global _verifier, _verifier_key
    with _build_lock:
        _verifier = None
        _verifier_key = None
