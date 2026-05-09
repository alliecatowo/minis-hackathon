"""Dev.to blog ingestion source plugin.

Fetches a developer's published articles from the Dev.to API and formats them
as evidence for personality analysis. Blog posts reveal in-depth technical
knowledge, teaching style, and opinions on technology choices.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from app.plugins.base import EvidenceItem, IngestionSource

logger = logging.getLogger(__name__)

_DEVTO_API = "https://dev.to/api"
_MAX_ARTICLES = 30
_EXCERPT_LENGTH = 1500


class DevBlogSource(IngestionSource):
    """Ingestion source that fetches Dev.to articles for a username."""

    name = "devblog"

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per Dev.to article.

        external_id: ``devto:{article_id}``
        Items already present in ``since_external_ids`` are skipped.
        """
        since = since_external_ids or set()

        max_articles = _MAX_ARTICLES
        async with httpx.AsyncClient(timeout=30) as client:
            articles = await _fetch_articles(client, identifier, max_articles)
            detailed = await _fetch_article_bodies(client, articles)

        for article in detailed:
            article_id = article.get("id")
            if not article_id:
                continue
            external_id = f"devto:{article_id}"
            if external_id in since:
                continue

            title = article.get("title") or "Untitled"
            published = (article.get("published_at") or "")[:10]
            tags = article.get("tag_list") or article.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            reactions = article.get("positive_reactions_count", 0)
            comments = article.get("comments_count", 0)
            body = article.get("body_markdown") or article.get("description") or ""
            if len(body) > _EXCERPT_LENGTH:
                body = body[:_EXCERPT_LENGTH] + "..."

            content_parts: list[str] = [f"Title: {title}"]
            if published:
                content_parts.append(f"Published: {published}")
            if tags:
                content_parts.append(f"Tags: {', '.join(tags)}")
            content_parts.append(f"Reactions: {reactions}, Comments: {comments}")
            if body:
                content_parts.append(body)

            # Parse evidence_date from published_at if available
            evidence_date = None
            published_at = article.get("published_at")
            if published_at:
                try:
                    evidence_date = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            # source_uri is the Dev.to article URL
            source_uri = article.get("url")

            # raw_context_json: Dev.to article metadata
            raw_context = {
                "positive_reactions_count": reactions,
                "comments_count": comments,
                "tags": tags,
            }
            if article.get("user", {}).get("name"):
                raw_context["author"] = article["user"]["name"]

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="article",
                content="\n".join(content_parts),
                context="devto_article",
                evidence_date=evidence_date,
                source_uri=source_uri,
                raw_context=raw_context,
                metadata={
                    "article_id": article_id,
                    "title": title,
                    "published_at": published,
                    "tags": tags,
                    "reactions": reactions,
                },
                privacy="public",
            )


async def _fetch_articles(
    client: httpx.AsyncClient, username: str, limit: int
) -> list[dict[str, Any]]:
    """Fetch article listing for a Dev.to user."""
    articles: list[dict[str, Any]] = []
    page = 1
    per_page = min(limit, 30)

    while len(articles) < limit:
        resp = await client.get(
            f"{_DEVTO_API}/articles",
            params={"username": username, "per_page": per_page, "page": page},
        )
        if resp.status_code != 200:
            logger.warning("Dev.to API returned %d for user %s", resp.status_code, username)
            break

        batch = resp.json()
        if not batch:
            break

        articles.extend(batch)
        page += 1

    return articles[:limit]


async def _fetch_article_bodies(
    client: httpx.AsyncClient, articles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch full body_markdown for each article."""
    detailed: list[dict[str, Any]] = []

    for article in articles:
        article_id = article.get("id")
        if not article_id:
            continue

        try:
            resp = await client.get(f"{_DEVTO_API}/articles/{article_id}")
            if resp.status_code == 200:
                detailed.append(resp.json())
            else:
                # Fall back to listing data (no body_markdown)
                detailed.append(article)
        except httpx.HTTPError:
            logger.warning("Failed to fetch Dev.to article %s", article_id)
            detailed.append(article)

    return detailed
