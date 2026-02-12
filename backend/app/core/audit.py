"""Structured JSON audit logging.

Provides a dedicated audit logger that writes structured JSON records for
security-relevant events: auth, access control, rate limiting, and admin actions.

Uses Python's standard logging module with a JSON formatter so records can be
ingested by any log aggregation system.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class _JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
        }

        # Merge extra fields passed via `extra={"audit": {...}}`
        audit_data = getattr(record, "audit", None)
        if isinstance(audit_data, dict):
            log_data.update(audit_data)

        return json.dumps(log_data, default=str)


def _setup_audit_logger() -> logging.Logger:
    """Create and configure the audit logger with JSON formatting."""
    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    # Only add handler if not already present (avoid duplicates on reload)
    if not audit_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JSONFormatter())
        audit_logger.addHandler(handler)

    return audit_logger


_audit = _setup_audit_logger()


def log_auth_event(
    action: str,
    *,
    user_id: str | None = None,
    username: str | None = None,
    ip: str | None = None,
    success: bool = True,
    detail: str | None = None,
) -> None:
    """Log an authentication event (login, logout, token refresh, failed attempt)."""
    _audit.info(
        "auth_event",
        extra={
            "audit": {
                "category": "auth",
                "action": action,
                "user_id": user_id,
                "username": username,
                "ip": ip,
                "success": success,
                "detail": detail,
            }
        },
    )


def log_access_denied(
    *,
    path: str,
    method: str,
    user_id: str | None = None,
    ip: str | None = None,
    reason: str | None = None,
) -> None:
    """Log an access control denial (403)."""
    _audit.warning(
        "access_denied",
        extra={
            "audit": {
                "category": "access",
                "path": path,
                "method": method,
                "user_id": user_id,
                "ip": ip,
                "reason": reason,
            }
        },
    )


def log_rate_limit(
    *,
    ip: str | None = None,
    user_id: str | None = None,
    path: str | None = None,
    limit: int | None = None,
    window: str | None = None,
) -> None:
    """Log a rate limit hit (429)."""
    _audit.warning(
        "rate_limit_hit",
        extra={
            "audit": {
                "category": "rate_limit",
                "ip": ip,
                "user_id": user_id,
                "path": path,
                "limit": limit,
                "window": window,
            }
        },
    )


def log_admin_action(
    action: str,
    *,
    user_id: str,
    username: str | None = None,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    """Log an admin action."""
    _audit.info(
        "admin_action",
        extra={
            "audit": {
                "category": "admin",
                "action": action,
                "user_id": user_id,
                "username": username,
                "target": target,
                "detail": detail,
            }
        },
    )


def log_security_event(
    event: str,
    *,
    ip: str | None = None,
    user_id: str | None = None,
    detail: str | None = None,
    severity: str = "warning",
) -> None:
    """Log a general security event (prompt injection, suspicious pattern, etc.)."""
    level = getattr(logging, severity.upper(), logging.WARNING)
    _audit.log(
        level,
        "security_event",
        extra={
            "audit": {
                "category": "security",
                "event": event,
                "ip": ip,
                "user_id": user_id,
                "detail": detail,
            }
        },
    )
