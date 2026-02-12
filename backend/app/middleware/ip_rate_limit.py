"""IP-based sliding window rate limiting middleware.

Uses an in-memory dict with TTL cleanup -- no Redis needed.
Applies different limits based on request context:
- Unauthenticated requests: 60 req/min per IP
- Authenticated requests: 300 req/min per user
- Auth endpoints: 10 attempts/min per IP
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

# Limits: (max_requests, window_seconds)
UNAUTH_LIMIT = (60, 60)  # 60 req/min per IP
AUTH_LIMIT = (300, 60)  # 300 req/min per user
AUTH_ENDPOINT_LIMIT = (10, 60)  # 10 attempts/min per IP

_AUTH_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/callback",
    "/api/auth/token",
    "/api/auth/refresh",
})

# Paths to skip (health checks, static assets)
_SKIP_PATHS = frozenset({"/api/health", "/docs", "/redoc", "/openapi.json"})

# ── Sliding window storage ───────────────────────────────────────────────────

# key -> list of request timestamps
_windows: dict[str, list[float]] = defaultdict(list)

# Track last cleanup time to avoid cleaning on every request
_last_cleanup = 0.0
_CLEANUP_INTERVAL = 30.0  # Run cleanup every 30 seconds


def _cleanup_expired() -> None:
    """Remove expired entries from the sliding window dict."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    max_window = 60  # Largest window we use
    cutoff = now - max_window
    keys_to_delete: list[str] = []
    for key, timestamps in _windows.items():
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if not timestamps:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del _windows[key]


def _check_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Check if a key is within its rate limit. Returns True if allowed."""
    now = time.monotonic()
    cutoff = now - window_seconds
    timestamps = _windows[key]

    # Prune expired entries
    timestamps[:] = [t for t in timestamps if t > cutoff]

    if len(timestamps) >= max_requests:
        return False

    timestamps.append(now)
    return True


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter based on IP, user, or auth endpoint."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip non-API and health paths
        if path in _SKIP_PATHS or not path.startswith("/api"):
            return await call_next(request)

        # Periodic cleanup
        _cleanup_expired()

        ip = request.client.host if request.client else "unknown"

        # 1. Auth endpoint rate limit (strictest)
        if path in _AUTH_PATHS:
            key = f"auth:{ip}"
            max_req, window = AUTH_ENDPOINT_LIMIT
            if not _check_limit(key, max_req, window):
                logger.warning(
                    "Auth rate limit exceeded: ip=%s path=%s", ip, path
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Too many authentication attempts. Limit: {max_req} per {window}s."
                    },
                )

        # 2. Check for authenticated user (via Authorization header presence)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # Authenticated: rate limit by a hash of the token to avoid storing raw tokens
            # Use a truncated token as key (first 16 chars of the bearer value)
            token_prefix = auth_header[7:23]
            key = f"user:{token_prefix}"
            max_req, window = AUTH_LIMIT
        else:
            # Unauthenticated: rate limit by IP
            key = f"ip:{ip}"
            max_req, window = UNAUTH_LIMIT

        if not _check_limit(key, max_req, window):
            logger.warning(
                "Rate limit exceeded: key=%s path=%s", key.split(":")[0], path
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Limit: {max_req} requests per {window}s."
                },
            )

        return await call_next(request)
