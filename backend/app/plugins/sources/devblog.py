"""Dev.to blog ingestion source plugin.

Fetches a developer's published articles from the Dev.to API and formats them
as evidence for personality analysis. Blog posts reveal in-depth technical
knowledge, teaching style, and opinions on technology choices.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

_DEVTO_API = "https://dev.to/api"
_MAX_ARTICLES = 30
_EXCERPT_LENGTH = 1500


class DevBlogSource(IngestionSource):
    """Ingestion source that fetches Dev.to articles for a username."""

    name = "devblog"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch Dev.to articles and format as evidence.

        Args:
            identifier: Dev.to username.
        """
        max_articles = config.get("max_articles", _MAX_ARTICLES)

        async with httpx.AsyncClient(timeout=30) as client:
            articles = await _fetch_articles(client, identifier, max_articles)
            detailed = await _fetch_article_bodies(client, articles)

        evidence = _format_evidence(identifier, detailed)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "article_count": len(detailed),
                "articles": [
                    {
                        "title": a["title"],
                        "tags": a.get("tag_list", []),
                        "published_at": a.get("published_at", ""),
                        "positive_reactions_count": a.get("positive_reactions_count", 0),
                    }
                    for a in detailed
                ],
            },
            stats={
                "articles_fetched": len(detailed),
                "total_reactions": sum(a.get("positive_reactions_count", 0) for a in detailed),
                "total_comments": sum(a.get("comments_count", 0) for a in detailed),
                "evidence_length": len(evidence),
            },
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


def _format_evidence(username: str, articles: list[dict[str, Any]]) -> str:
    """Format Dev.to articles into evidence text for LLM personality analysis."""
    if not articles:
        return ""

    sections: list[str] = [
        "## Dev.to Articles\n"
        "(Developer blog posts reveal in-depth technical knowledge, teaching style,\n"
        "and opinions on technology choices.)\n"
    ]

    for article in articles:
        title = article.get("title", "Untitled")
        published = article.get("published_at", "")[:10]
        tags = article.get("tag_list") or article.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        tag_str = ", ".join(tags) if tags else "untagged"
        reactions = article.get("positive_reactions_count", 0)
        comments = article.get("comments_count", 0)

        body = article.get("body_markdown") or article.get("description") or ""
        excerpt = body[:_EXCERPT_LENGTH]
        if len(body) > _EXCERPT_LENGTH:
            excerpt += "..."

        sections.append(
            f'### "{title}" ({published}) [{tag_str}] '
            f"({reactions} reactions, {comments} comments)"
        )
        if excerpt:
            sections.append(f"> {excerpt}")
        sections.append("")

    return "\n".join(sections)
