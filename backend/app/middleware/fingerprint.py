"""Request fingerprinting middleware.

Hashes User-Agent + Accept-Language + IP prefix (/24) to produce a
semi-stable fingerprint for each client. The fingerprint is stored on
request.state.fingerprint for downstream use (abuse correlation,
credential stuffing detection).
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Credential stuffing detection: track failed auth attempts per fingerprint
# fingerprint -> list of timestamps of recent failures
_auth_failures: dict[str, list[float]] = defaultdict(list)

# Thresholds for credential stuffing detection
_STUFFING_WINDOW = 300.0  # 5 minutes
_STUFFING_THRESHOLD = 10  # failures per window
_AUTH_PATHS = {"/api/auth/login", "/api/auth/callback", "/api/auth/token"}


def _ip_prefix(ip: str) -> str:
    """Extract /24 prefix from an IPv4 address, or use the full IPv6 /48."""
    if ":" in ip:
        # IPv6: use first 3 groups (/48)
        parts = ip.split(":")
        return ":".join(parts[:3])
    # IPv4: use first 3 octets (/24)
    parts = ip.split(".")
    return ".".join(parts[:3])


def compute_fingerprint(
    user_agent: str, accept_language: str, ip: str
) -> str:
    """Compute a SHA-256 fingerprint from request signals."""
    raw = f"{user_agent}|{accept_language}|{_ip_prefix(ip)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class FingerprintMiddleware(BaseHTTPMiddleware):
    """Add a request fingerprint to request.state for downstream use."""

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "")
        accept_language = request.headers.get("accept-language", "")

        fingerprint = compute_fingerprint(user_agent, accept_language, ip)
        request.state.fingerprint = fingerprint

        response = await call_next(request)

        # Detect credential stuffing on auth endpoints
        if request.url.path in _AUTH_PATHS and response.status_code in (401, 403):
            now = time.monotonic()
            failures = _auth_failures[fingerprint]
            # Prune old entries
            failures[:] = [t for t in failures if now - t < _STUFFING_WINDOW]
            failures.append(now)

            if len(failures) >= _STUFFING_THRESHOLD:
                logger.warning(
                    "Credential stuffing suspected: fingerprint=%s failures=%d in %.0fs",
                    fingerprint,
                    len(failures),
                    _STUFFING_WINDOW,
                )

        return response
