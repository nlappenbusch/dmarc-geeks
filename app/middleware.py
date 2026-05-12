"""Lightweight middleware: request-id correlation, access logging, security headers."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger("dmarc.access")


_CSP_BASE = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https:; "          # allow whitelabel logos from any HTTPS host
    "connect-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "  # sourcemaps from CDNs
    "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com; "  # YT + eigene iframes (z.B. /embed/mailtest)
    "base-uri 'self'; "
    "form-action 'self'"
)

# Default CSP für alles ausser /embed/*: frame-ancestors verbieten
# (clickjacking-Schutz für Auth-Seiten, Dashboards, etc.)
_CSP_DEFAULT = _CSP_BASE + "; frame-ancestors 'none'"

# CSP für /embed/* Routen: frame-ancestors *: Partner dürfen embedden
_CSP_EMBED = _CSP_BASE + "; frame-ancestors *"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds defensive HTTP headers to every response.

    Spezialfall fuer /embed/* Routen: dort wollen wir embeddability erlauben,
    deshalb wird X-Frame-Options nicht gesetzt und CSP-frame-ancestors auf *
    erweitert. Damit kann z.B. ein Partner unser Mail-Tester-Widget per iframe
    auf seiner Website einbetten."""

    async def dispatch(self, request: Request, call_next) -> Response:
        is_embed = request.url.path.startswith("/embed/")
        response = await call_next(request)
        if is_embed:
            response.headers.setdefault("Content-Security-Policy", _CSP_EMBED)
            # NICHT X-Frame-Options setzen -> Browser nutzt CSP frame-ancestors
        else:
            response.headers.setdefault("Content-Security-Policy", _CSP_DEFAULT)
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy",
                                     "geolocation=(), microphone=(), camera=(), payment=()")
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds X-Request-ID header on every response and logs access lines."""

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            ms = int((time.monotonic() - start) * 1000)
            log.exception("[%s] %s %s -> error in %sms", rid, request.method, request.url.path, ms)
            raise
        ms = int((time.monotonic() - start) * 1000)
        if not request.url.path.startswith("/static/"):
            log.info("[%s] %s %s -> %s in %sms",
                     rid, request.method, request.url.path, response.status_code, ms)
        response.headers["X-Request-ID"] = rid
        return response
