"""Bearer-token middleware for the EduScheduler API.

Threat model: this CRM runs on a Tailscale-internal network with a
single tenant, so the realistic threat is *another service on the same
Docker host* hitting the API by accident — not random internet traffic.
The middleware therefore enforces a token only on the cross-service
path; same-origin browser requests (the bundled SPA) flow through
without the user having to log in.

Algorithm:
  1. Allow every non-/api/* path (static frontend assets).
  2. Allow /api/healthz and /api/_meta — public diagnostic endpoints.
  3. If `Sec-Fetch-Site: same-origin` is present → allow. Modern
     browsers always set this header on fetch/XHR; server-to-server
     callers (Python requests, curl, internal containers) don't.
  4. Otherwise require `Authorization: Bearer <EDSCHEDULER_API_TOKEN>`.
  5. If `EDSCHEDULER_API_TOKEN` env var is unset, fail open with a
     log line — preserves dev workflow but warns loudly.

Korifi services that call into EduScheduler get the token via env var
and add it to every outgoing request through
`src/integrations/edscheduler_client.py`.
"""
from __future__ import annotations

import hmac
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_log = logging.getLogger(__name__)

_PUBLIC_API_PATHS = ("/api/healthz",)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Frontend assets and public API endpoints — no auth needed
        if not path.startswith("/api/"):
            return await call_next(request)
        if path in _PUBLIC_API_PATHS:
            return await call_next(request)

        # Same-origin browser request (the bundled SPA) — no auth needed.
        # Two signals, because browsers only send Sec-Fetch-* to "potentially
        # trustworthy" origins (HTTPS or localhost): over plain HTTP on a
        # Tailscale IP they omit it, so we also accept an Origin/Referer
        # that matches the host we're being addressed as. Both are client
        # headers — the real boundary is the host firewall (LAN blocked,
        # Tailscale only) + the bearer token for cross-service calls.
        if request.headers.get("sec-fetch-site") in ("same-origin", "same-site"):
            return await call_next(request)
        own_host = request.headers.get("host", "")
        for hdr in ("origin", "referer"):
            value = request.headers.get(hdr, "")
            if value and own_host and value.split("://", 1)[-1].split("/", 1)[0] == own_host:
                return await call_next(request)

        expected = os.environ.get("EDSCHEDULER_API_TOKEN", "").strip()
        if not expected:
            # Fail-closed: an unset token must lock cross-service access,
            # never silently expose student data.
            _log.error(
                "EDSCHEDULER_API_TOKEN unset — rejecting cross-service API "
                "calls (fail-closed). Set the env var and restart."
            )
            return JSONResponse(
                {"detail": "Server token not configured"},
                status_code=503,
            )

        provided = request.headers.get("authorization", "")
        if not provided.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Missing Authorization: Bearer <token>"},
                status_code=401,
            )
        if not hmac.compare_digest(provided.removeprefix("Bearer ").strip(), expected):
            return JSONResponse(
                {"detail": "Invalid bearer token"},
                status_code=401,
            )

        return await call_next(request)
