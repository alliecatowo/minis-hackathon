"""Minis GitHub App — webhook server for PR reviews by AI personality clones."""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from app.config import settings
from app.webhooks import (
    handle_issue_comment,
    handle_pr_review_comment,
    handle_pull_request_opened,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Minis GitHub App", version="0.1.0")


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """Verify the webhook payload against the GitHub signature."""
    if not settings.github_webhook_secret:
        # No secret configured — skip verification (dev mode)
        return True

    expected = hmac.new(
        settings.github_webhook_secret.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


@app.get("/health")
async def health():
    return {"status": "ok", "app": "minis-github-app"}


@app.post("/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_hub_signature_256: str = Header(None),
):
    """Receive and dispatch GitHub webhook events."""
    body = await request.body()

    # Verify signature
    if x_hub_signature_256 and not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    action = payload.get("action", "")

    logger.info("Received event: %s.%s", x_github_event, action)

    # Dispatch events — run in background so we respond 200 quickly
    import asyncio

    if x_github_event == "pull_request" and action == "opened":
        asyncio.create_task(_safe_handle(handle_pull_request_opened, payload))

    elif x_github_event == "pull_request" and action == "review_requested":
        # Also trigger review when reviewers are added after PR is opened
        asyncio.create_task(_safe_handle(handle_pull_request_opened, payload))

    elif x_github_event == "issue_comment" and action == "created":
        asyncio.create_task(_safe_handle(handle_issue_comment, payload))

    elif x_github_event == "pull_request_review_comment" and action == "created":
        asyncio.create_task(_safe_handle(handle_pr_review_comment, payload))

    else:
        logger.debug("Ignoring event: %s.%s", x_github_event, action)

    return {"status": "ok"}


async def _safe_handle(handler, payload: dict) -> None:
    """Wrap handler in try/except so background tasks don't crash silently."""
    try:
        await handler(payload)
    except Exception:
        logger.exception("Error handling webhook event")
