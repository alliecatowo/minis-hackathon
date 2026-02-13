"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.formatter import format_evidence
from app.ingestion.github import GitHubData, fetch_github_data
from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)


async def _get_cached(session: AsyncSession, mini_id: str, source_name: str, data_key: str) -> Any | None:
    """Check for valid cached data."""
    from app.models.ingestion_data import IngestionData

    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == mini_id,
            IngestionData.source_name == source_name,
            IngestionData.data_key == data_key,
        )
    )
    cached = result.scalar_one_or_none()
    if cached and cached.expires_at and cached.expires_at > datetime.now(timezone.utc):
        return json.loads(cached.data_json)
    return None


async def _save_cache(
    session: AsyncSession, mini_id: str, source_name: str, data_key: str, data: Any, ttl_hours: int = 24
) -> None:
    """Save or update cached data."""
    from app.models.ingestion_data import IngestionData

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == mini_id,
            IngestionData.source_name == source_name,
            IngestionData.data_key == data_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.data_json = json.dumps(data)
        existing.fetched_at = now
        existing.expires_at = expires
    else:
        entry = IngestionData(
            mini_id=mini_id,
            source_name=source_name,
            data_key=data_key,
            data_json=json.dumps(data),
            fetched_at=now,
            expires_at=expires,
        )
        session.add(entry)
    await session.flush()


class GitHubSource(IngestionSource):
    """Ingestion source that fetches GitHub activity for a username."""

    name = "github"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch GitHub data and format as evidence.

        If mini_id is provided in config, caches raw API data in IngestionData
        for faster re-creation. Falls back to direct fetch when no caching context.

        Args:
            identifier: GitHub username.
            **config: Optional mini_id (int) for caching.
        """
        mini_id: str | None = config.get("mini_id")
        db_session: AsyncSession | None = config.get("session")

        use_cache = mini_id is not None and db_session is not None

        if use_cache:
            github_data = await self._fetch_with_cache(identifier, mini_id, db_session)  # type: ignore[arg-type]
        else:
            github_data = await fetch_github_data(identifier)

        evidence = format_evidence(github_data)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "profile": github_data.profile,
                "repos_summary": {
                    "languages": _aggregate_languages(github_data),
                    "primary_languages": _aggregate_primary_languages(github_data),
                    "repo_count": len(github_data.repos),
                    "top_repos": [
                        {
                            "name": r.get("name"),
                            "full_name": r.get("full_name"),
                            "description": r.get("description"),
                            "language": r.get("language"),
                            "stargazers_count": r.get("stargazers_count", 0),
                            "topics": r.get("topics", []),
                        }
                        for r in github_data.repos
                    ],
                },
                # Full data for explorer deep-dive tools
                "pull_requests_full": github_data.pull_requests,
                "review_comments_full": github_data.review_comments,
                "issue_comments_full": github_data.issue_comments,
                "commits_full": github_data.commits,
            },
            stats={
                "repos_count": len(github_data.repos),
                "commits_analyzed": len(github_data.commits),
                "prs_analyzed": len(github_data.pull_requests),
                "reviews_analyzed": len(github_data.review_comments),
                "issue_comments_analyzed": len(github_data.issue_comments),
                "evidence_length": len(evidence),
            },
        )

    async def _fetch_with_cache(
        self, identifier: str, mini_id: str, session: AsyncSession
    ) -> GitHubData:
        """Fetch GitHub data, using IngestionData cache where available."""
        # Try loading all cached pieces
        cached_profile = await _get_cached(session, mini_id, "github", "profile")
        cached_repos = await _get_cached(session, mini_id, "github", "repos")
        cached_commits = await _get_cached(session, mini_id, "github", "commits")
        cached_reviews = await _get_cached(session, mini_id, "github", "review_comments")

        # If all cached, reconstruct GitHubData directly
        if all(v is not None for v in [cached_profile, cached_repos, cached_commits, cached_reviews]):
            logger.info("Using fully cached GitHub data for %s (mini_id=%d)", identifier, mini_id)
            cached_languages = await _get_cached(session, mini_id, "github", "repo_languages") or {}
            cached_prs = await _get_cached(session, mini_id, "github", "pull_requests") or []
            cached_issue_comments = await _get_cached(session, mini_id, "github", "issue_comments") or []
            return GitHubData(
                profile=cached_profile,
                repos=cached_repos,
                commits=cached_commits,
                pull_requests=cached_prs,
                review_comments=cached_reviews,
                issue_comments=cached_issue_comments,
                repo_languages=cached_languages,
            )

        # Cache miss — fetch fresh and save
        logger.info("Cache miss for %s (mini_id=%d), fetching from GitHub API", identifier, mini_id)
        github_data = await fetch_github_data(identifier)

        # Save each piece with appropriate TTLs
        await _save_cache(session, mini_id, "github", "profile", github_data.profile, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "repos", github_data.repos, ttl_hours=168)
        await _save_cache(session, mini_id, "github", "commits", github_data.commits, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "pull_requests", github_data.pull_requests, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "review_comments", github_data.review_comments, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "issue_comments", github_data.issue_comments, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "repo_languages", github_data.repo_languages, ttl_hours=168)

        return github_data


def _aggregate_languages(github_data: GitHubData) -> dict[str, int]:
    """Aggregate language byte counts across all repos into a sorted summary."""
    totals: dict[str, int] = {}
    for lang_map in github_data.repo_languages.values():
        for lang, byte_count in lang_map.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    # Sort by bytes descending
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def _aggregate_primary_languages(github_data: GitHubData) -> dict[str, int]:
    """Count repos by their primary language across ALL repos."""
    counts: dict[str, int] = {}
    for repo in github_data.repos:
        lang = repo.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
