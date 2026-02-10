"""GitHub API client for fetching PRs and posting reviews.

Handles GitHub App authentication (JWT + installation tokens) and provides
methods for the PR review workflow.
"""

from __future__ import annotations

import logging
import time

import httpx
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Cache installation tokens (they last 1 hour)
_token_cache: dict[int, tuple[str, float]] = {}


def _get_private_key() -> str:
    """Load the private key from settings (PEM string or file path)."""
    key = settings.github_private_key
    if key.startswith("-----BEGIN"):
        return key
    # Treat as file path
    with open(key) as f:
        return f.read()


def _generate_jwt() -> str:
    """Generate a JWT for GitHub App authentication."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    private_key = _get_private_key()
    return jwt.encode(payload, private_key, algorithm="RS256")


async def _get_installation_token(installation_id: int) -> str:
    """Get an installation access token, using cache if valid."""
    cached = _token_cache.get(installation_id)
    if cached:
        token, expires_at = cached
        if time.time() < expires_at - 60:
            return token

    app_jwt = _generate_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    token = data["token"]
    # Tokens last 1 hour; cache for 50 minutes
    _token_cache[installation_id] = (token, time.time() + 3000)
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


async def get_pr_diff(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> str:
    """Fetch the diff for a pull request."""
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers={
                **_auth_headers(token),
                "Accept": "application/vnd.github.diff",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.text


async def get_pr_details(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> dict:
    """Fetch PR metadata (title, body, author, etc.)."""
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=_auth_headers(token),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_pr_requested_reviewers(
    installation_id: int, owner: str, repo: str, pr_number: int
) -> list[str]:
    """Get the list of requested reviewer usernames for a PR."""
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers",
            headers=_auth_headers(token),
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [u["login"] for u in data.get("users", [])]


async def post_pr_review(
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    event: str = "COMMENT",
) -> dict:
    """Post a PR review comment.

    Args:
        event: One of "APPROVE", "REQUEST_CHANGES", "COMMENT"
    """
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=_auth_headers(token),
            json={"body": body, "event": event},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()


async def post_issue_comment(
    installation_id: int, owner: str, repo: str, issue_number: int, body: str
) -> dict:
    """Post a comment on an issue or PR."""
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
            headers=_auth_headers(token),
            json={"body": body},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()


async def get_issue_comment(
    installation_id: int, owner: str, repo: str, comment_id: int
) -> dict:
    """Fetch a specific issue comment."""
    token = await _get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/comments/{comment_id}",
            headers=_auth_headers(token),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
