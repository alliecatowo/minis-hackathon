"""Web client plugin — the existing Next.js frontend routes.

This is a thin wrapper that registers the existing chat and minis routes
as the "web" client plugin. It serves as the reference implementation.
"""

from __future__ import annotations

from typing import Any

from app.plugins.base import ClientPlugin


class WebClient(ClientPlugin):
    """The default web client — existing FastAPI routes serve the Next.js frontend."""

    name = "web"

    async def setup(self, app: Any) -> None:
        """No-op: web routes are already registered in main.py."""
        pass
