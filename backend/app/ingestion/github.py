"""GitHub API client for fetching user activity data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


@dataclass
class GitHubData:
    """Container for all fetched GitHub data for a user."""

    profile: dict[str, Any] = field(default_factory=dict)
    repos: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    pull_requests: list[dict[str, Any]] = field(default_factory=list)
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    issue_comments: list[dict[str, Any]] = field(default_factory=list)
    repo_languages: dict[str, dict[str, int]] = field(default_factory=dict)


def _headers() -> dict[str, str]:
    # mercy-preview enables topics array on repository objects
    headers = {"Accept": "application/vnd.github.mercy-preview+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
    """Make a GET request, handling rate limits and errors."""
    resp = await client.get(url, params=params)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        logger.warning("GitHub rate limit hit for %s", url)
        return None
    if resp.status_code == 422:
        # GitHub search validation error — skip
        logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
        return None
    resp.raise_for_status()
    return resp.json()


async def fetch_github_data(username: str) -> GitHubData:
    """Fetch all available GitHub activity for a user."""
    data = GitHubData()

    async with httpx.AsyncClient(
        base_url=API_BASE, headers=_headers(), timeout=30.0
    ) as client:
        # 1. User profile
        profile = await _get(client, f"/users/{username}")
        if profile:
            data.profile = profile

        # 2. Repos (top 30 by recent push, with topics)
        repos = await _get(
            client,
            f"/users/{username}/repos",
            params={"sort": "pushed", "per_page": "30", "type": "owner"},
        )
        if repos:
            data.repos = repos

            # 2b. Per-repo language breakdown for top 10 repos
            for repo in repos[:10]:
                repo_name = repo.get("full_name") or repo.get("name", "")
                if not repo_name:
                    continue
                langs = await _get(client, f"/repos/{repo_name}/languages")
                if langs and isinstance(langs, dict):
                    data.repo_languages[repo_name] = langs

        # 3. Recent commits (search API)
        commits_resp = await _get(
            client,
            "/search/commits",
            params={
                "q": f"author:{username}",
                "sort": "author-date",
                "per_page": "50",
            },
        )
        if commits_resp and "items" in commits_resp:
            data.commits = commits_resp["items"]

        # 4. PRs authored
        prs_resp = await _get(
            client,
            "/search/issues",
            params={
                "q": f"author:{username} type:pr",
                "sort": "updated",
                "per_page": "30",
            },
        )
        if prs_resp and "items" in prs_resp:
            data.pull_requests = prs_resp["items"]

        # 5. Review comments — fetch from recent PR-related events
        # Use the events API to find IssueCommentEvent and PullRequestReviewCommentEvent
        events = await _get(
            client,
            f"/users/{username}/events",
            params={"per_page": "100"},
        )
        if events:
            for event in events:
                etype = event.get("type", "")
                payload = event.get("payload", {})
                if etype == "PullRequestReviewCommentEvent":
                    comment = payload.get("comment", {})
                    if comment:
                        data.review_comments.append(comment)
                elif etype == "IssueCommentEvent":
                    comment = payload.get("comment", {})
                    if comment:
                        data.issue_comments.append(comment)

        # 6. If no review comments from events, try search
        if not data.review_comments:
            review_resp = await _get(
                client,
                "/search/issues",
                params={
                    "q": f"commenter:{username} type:pr",
                    "sort": "updated",
                    "per_page": "20",
                },
            )
            if review_resp and "items" in review_resp:
                # Fetch review comments from these PRs
                for pr in review_resp["items"][:5]:
                    pr_url = pr.get("pull_request", {}).get("url", "")
                    if pr_url:
                        comments = await _get(
                            client, f"{pr_url}/comments"
                        )
                        if comments:
                            for c in comments:
                                if (c.get("user", {}).get("login", "")).lower() == username.lower():
                                    data.review_comments.append(c)

    logger.info(
        "Fetched GitHub data for %s: %d repos, %d commits, %d PRs, %d reviews, %d issue comments, %d repo language breakdowns",
        username,
        len(data.repos),
        len(data.commits),
        len(data.pull_requests),
        len(data.review_comments),
        len(data.issue_comments),
        len(data.repo_languages),
    )
    return data
