"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.github import GitHubData, fetch_github_data
from app.plugins.base import EvidenceItem, IngestionSource

logger = logging.getLogger(__name__)


async def _get_cached(
    session: AsyncSession, mini_id: str, source_name: str, data_key: str
) -> Any | None:
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
    session: AsyncSession,
    mini_id: str,
    source_name: str,
    data_key: str,
    data: Any,
    ttl_hours: int = 24,
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
        if all(
            v is not None for v in [cached_profile, cached_repos, cached_commits, cached_reviews]
        ):
            logger.info("Using fully cached GitHub data for %s (mini_id=%s)", identifier, mini_id)
            cached_languages = await _get_cached(session, mini_id, "github", "repo_languages") or {}
            cached_prs = await _get_cached(session, mini_id, "github", "pull_requests") or []
            cached_issue_comments = (
                await _get_cached(session, mini_id, "github", "issue_comments") or []
            )
            cached_commit_diffs = (
                await _get_cached(session, mini_id, "github", "commit_diffs") or []
            )
            cached_pr_review_threads = (
                await _get_cached(session, mini_id, "github", "pr_review_threads") or []
            )
            cached_issue_threads = (
                await _get_cached(session, mini_id, "github", "issue_threads") or []
            )
            return GitHubData(
                profile=cached_profile,
                repos=cached_repos,
                commits=cached_commits,
                pull_requests=cached_prs,
                review_comments=cached_reviews,
                issue_comments=cached_issue_comments,
                repo_languages=cached_languages,
                commit_diffs=cached_commit_diffs,
                pr_review_threads=cached_pr_review_threads,
                issue_threads=cached_issue_threads,
            )

        # Cache miss — fetch fresh and save
        logger.info("Cache miss for %s (mini_id=%s), fetching from GitHub API", identifier, mini_id)
        github_data = await fetch_github_data(identifier)

        # Save each piece with appropriate TTLs
        await _save_cache(session, mini_id, "github", "profile", github_data.profile, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "repos", github_data.repos, ttl_hours=168)
        await _save_cache(session, mini_id, "github", "commits", github_data.commits, ttl_hours=24)
        await _save_cache(
            session, mini_id, "github", "pull_requests", github_data.pull_requests, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "review_comments", github_data.review_comments, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "issue_comments", github_data.issue_comments, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "repo_languages", github_data.repo_languages, ttl_hours=168
        )
        await _save_cache(
            session, mini_id, "github", "commit_diffs", github_data.commit_diffs, ttl_hours=24
        )
        await _save_cache(
            session,
            mini_id,
            "github",
            "pr_review_threads",
            github_data.pr_review_threads,
            ttl_hours=24,
        )
        await _save_cache(
            session, mini_id, "github", "issue_threads", github_data.issue_threads, ttl_hours=24
        )

        return github_data

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: AsyncSession | None,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per GitHub entity (commit, PR, review, issue comment).

        Uses the same cached GitHubData as ``_fetch_with_cache()`` so no additional
        API calls are made when the cache is warm.  Items whose external_id already appears in
        ``since_external_ids`` are skipped (incremental-fetch fast path).

        external_id shapes:
          - ``commit:{sha}``
          - ``pr:{owner}/{repo}#{number}``
          - ``review:{pr_node_id}#{review_id}``
          - ``issue_comment:{comment_id}``
        """
        since = since_external_ids or set()

        if session is not None:
            github_data = await self._fetch_with_cache(identifier, mini_id, session)
        else:
            github_data = await fetch_github_data(identifier)

        # ── Commits ─────────────────────────────────────────────────────────
        for commit in github_data.commits:
            sha = commit.get("sha") or commit.get("commit", {}).get("sha") or ""
            if not sha:
                continue
            external_id = f"commit:{sha}"
            if external_id in since:
                continue
            msg = commit.get("commit", {}).get("message") or commit.get("message") or ""
            author = (
                commit.get("author", {}).get("login")
                or commit.get("committer", {}).get("login")
                or commit.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            author_name = (
                commit.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            repo_name = commit.get("repository", {}).get("full_name", "")
            content_parts = [f"Commit: {sha[:12]}"]
            if repo_name:
                content_parts.append(f"Repository: {repo_name}")
            if author_name or author:
                content_parts.append(f"Author: {author_name or author}")
            content_parts.append(f"Message:\n{msg}")

            # Attach diff summary if available
            for diff in github_data.commit_diffs:
                if diff.get("sha") == sha:
                    files = diff.get("files", [])
                    if files:
                        changed = [f.get("filename", "") for f in files[:10]]
                        content_parts.append(f"Files changed: {', '.join(changed)}")
                    break

            date_str = commit.get("commit", {}).get("author", {}).get("date") or commit.get("commit", {}).get("committer", {}).get("date")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="commit",
                content="\n".join(content_parts),
                context="commit_message",
                evidence_date=evidence_date,
                source_uri=commit.get("html_url"),
                author_id=author,
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "sha": sha,
                    "repo": repo_name,
                    "author": author,
                    "author_name": author_name,
                },
                privacy="public",
            )

        # ── Pull Requests ────────────────────────────────────────────────────
        for pr in github_data.pull_requests:
            number = pr.get("number")
            repo = pr.get("base", {}).get("repo", {}).get("full_name") or pr.get("repo", "")
            if not number:
                continue
            external_id = f"pr:{repo}#{number}"
            if external_id in since:
                continue
            title = pr.get("title") or ""
            body = pr.get("body") or ""
            state = pr.get("state") or ""
            author = pr.get("user", {}).get("login") or ""
            content_parts = [
                f"Pull Request #{number}: {title}",
                f"Repository: {repo}",
                f"State: {state}",
            ]
            if body:
                content_parts.append(f"Description:\n{body[:2000]}")

            # Attach review thread data if available
            pr_node_id = pr.get("node_id") or str(number)
            for thread in github_data.pr_review_threads:
                if thread.get("pr_number") == number or thread.get("pr_node_id") == pr_node_id:
                    comments = thread.get("comments", [])
                    if comments:
                        thread_text = "\n".join(
                            f"  [{c.get('author', {}).get('login', '?')}]: {c.get('body', '')[:300]}"
                            for c in comments[:5]
                        )
                        content_parts.append(f"Review thread:\n{thread_text}")
                    break

            date_str = pr.get("created_at") or pr.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="pr",
                content="\n".join(content_parts),
                context="issue_discussion",
                evidence_date=evidence_date,
                source_uri=pr.get("html_url"),
                author_id=author,
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.9 if author else 0.7,
                },
                metadata={
                    "number": number,
                    "repo": repo,
                    "state": state,
                    "author": author,
                },
                privacy="public",
            )

        # ── Reviews ──────────────────────────────────────────────────────────
        for review in github_data.review_comments:
            review_id = review.get("id")
            pr_id = (
                review.get("pull_request_review_id")
                or review.get("pull_request_url", "").split("/")[-1]
                or "0"
            )
            if not review_id:
                continue
            external_id = f"review:{pr_id}#{review_id}"
            if external_id in since:
                continue
            body = review.get("body") or ""
            path = review.get("path") or ""
            diff_hunk = review.get("diff_hunk") or ""
            author = review.get("user", {}).get("login") or ""
            content_parts = [f"Review comment (id={review_id})"]
            if path:
                content_parts.append(f"File: {path}")
            if body:
                content_parts.append(f"Comment:\n{body[:1000]}")
            if diff_hunk:
                content_parts.append(f"Diff context:\n{diff_hunk[:500]}")

            date_str = review.get("submitted_at") or review.get("created_at") or review.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="review",
                content="\n".join(content_parts),
                context="code_review",
                evidence_date=evidence_date,
                source_uri=review.get("html_url"),
                author_id=author,
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "review_id": review_id,
                    "pr_id": str(pr_id),
                    "path": path,
                    "author": author,
                },
                privacy="public",
            )

        # ── Issue Comments ────────────────────────────────────────────────────
        for comment in github_data.issue_comments:
            comment_id = comment.get("id")
            if not comment_id:
                continue
            external_id = f"issue_comment:{comment_id}"
            if external_id in since:
                continue
            body = comment.get("body") or ""
            issue_url = comment.get("issue_url") or comment.get("html_url") or ""
            author = comment.get("user", {}).get("login") or ""
            content_parts = [f"Issue comment (id={comment_id})"]
            if issue_url:
                content_parts.append(f"Issue: {issue_url}")
            if body:
                content_parts.append(f"Comment:\n{body[:1000]}")

            date_str = comment.get("created_at") or comment.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="issue_comment",
                content="\n".join(content_parts),
                context="issue_discussion",
                evidence_date=evidence_date,
                source_uri=comment.get("html_url"),
                author_id=author,
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={"comment_id": comment_id, "author": author},
                privacy="public",
            )


def _parse_github_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

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
