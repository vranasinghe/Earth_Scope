"""Anonymous, cookie-bound job ownership and CSRF protection.

* ``es_session`` — 256-bit random token, HttpOnly, SameSite=Lax, path /api.
  Only its SHA-256 hash is stored (``owner_hash``); a leaked database does not
  reveal usable session tokens. Job ids are random UUIDs, but an id alone never
  grants access: every job endpoint also requires the owning session.
* ``es_csrf`` — random token readable by the page (double-submit cookie). Every
  state-changing job request must echo it in ``X-CSRF-Token``; a cross-site
  form or script cannot read it. Requests with a foreign ``Origin`` are refused.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from fastapi import Request, Response

from app.core.config import Settings
from app.utils.errors import EarthScopeError

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
CSRF_HEADER = "X-CSRF-Token"


class SessionRequiredError(EarthScopeError):
    status_code = 401
    error = "SESSION_REQUIRED"


class CsrfError(EarthScopeError):
    status_code = 403
    error = "CSRF_CHECK_FAILED"


def owner_hash(token: str) -> str:
    return hashlib.sha256(f"earthscope-owner:{token}".encode()).hexdigest()


def ip_hash(ip: str | None) -> str | None:
    return hashlib.sha256(f"earthscope-ip:{ip}".encode()).hexdigest() if ip else None


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token(request: Request, name: str) -> str | None:
    v = request.cookies.get(name)
    return v if v and TOKEN_RE.match(v) else None


def ensure_session(request: Request, response: Response, settings: Settings) -> tuple[str, str]:
    """Return (owner_hash, csrf_token), issuing fresh cookies when absent or malformed."""
    token = _token(request, settings.session_cookie_name)
    csrf = _token(request, settings.csrf_cookie_name)
    max_age = settings.session_max_age_days * 86400
    if token is None:
        token = secrets.token_urlsafe(32)
        response.set_cookie(settings.session_cookie_name, token, max_age=max_age, httponly=True,
                            secure=settings.session_cookie_secure, samesite="lax", path="/api")
    if csrf is None:
        csrf = secrets.token_urlsafe(32)
        response.set_cookie(settings.csrf_cookie_name, csrf, max_age=max_age, httponly=False,
                            secure=settings.session_cookie_secure, samesite="strict", path="/")
    return owner_hash(token), csrf


def require_owner(request: Request, settings: Settings) -> str:
    token = _token(request, settings.session_cookie_name)
    if token is None:
        raise SessionRequiredError(
            "No analysis session was found in this browser.",
            ["Open the Analysis Jobs page first (it starts a session), and allow cookies for this site."],
        )
    return owner_hash(token)


def require_csrf(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in {o.rstrip("/") for o in settings.cors_origin_list} \
            and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise CsrfError("This request came from a page that is not allowed to manage analysis jobs.")
    cookie = _token(request, settings.csrf_cookie_name)
    header = request.headers.get(CSRF_HEADER, "")
    if cookie is None or not hmac.compare_digest(cookie, header):
        raise CsrfError("The request is missing its CSRF token. Reload the page and try again.")
