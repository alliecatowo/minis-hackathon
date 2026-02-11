"""HackerNews ingestion source plugin — fetches comments and submissions via Algolia API."""

from __future__ import annotations

import re
from typing import Any

import httpx

from app.plugins.base import IngestionResult, IngestionSource

_HN_API_BASE = "https://hn.algolia.com/api/v1"

# Reuse the same conflict/emotion detection patterns from the GitHub formatter
_CONFLICT_PATTERNS = re.compile(
    r"(?i)"
    r"(?:i disagree|i don't think|i wouldn't|actually,?\s|but\s|however,?\s"
    r"|nit:|nit\b|instead,?\s|why not|shouldn't we|have you considered"
    r"|i'd prefer|i'd rather|the problem with|this breaks|this will cause"
    r"|strongly feel|concerned about|not a fan of|pushback|blocker"
    r"|LGTM.*but|approve.*but|let's not|please don't|we should avoid"
    r"|hard disagree|respectfully)"
)

_STRONG_EMOTION_PATTERNS = re.compile(
    r"(?:"
    r"[A-Z]{3,}|!!+|[!?]{2,}"
    r"|:\)|:\(|:D|<3|:3|;\)|xD|lol|lmao|haha"
    r"|\b(?:love|hate|amazing|terrible|awesome|awful|perfect|horrible)\b"
    r")"
)


class HackerNewsSource(IngestionSource):
    """Ingestion source that fetches HackerNews activity for a username."""

    name = "hackernews"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch HackerNews comments and submissions, format as evidence.

        Args:
            identifier: HackerNews username.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            comments, stories = await _fetch_hn_data(client, identifier)

        evidence = _format_hn_evidence(identifier, comments, stories)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "comments_count": len(comments),
                "stories_count": len(stories),
            },
            stats={
                "comments_fetched": len(comments),
                "stories_fetched": len(stories),
                "evidence_length": len(evidence),
            },
        )


async def _fetch_hn_data(
    client: httpx.AsyncClient, username: str
) -> tuple[list[dict], list[dict]]:
    """Fetch comments and story submissions for a HN user in parallel."""
    comments_url = (
        f"{_HN_API_BASE}/search?tags=comment,author_{username}&hitsPerPage=100"
    )
    stories_url = (
        f"{_HN_API_BASE}/search?tags=story,author_{username}&hitsPerPage=50"
    )

    comments_resp, stories_resp = await _parallel_get(client, comments_url, stories_url)

    comments = comments_resp.get("hits", []) if comments_resp else []
    stories = stories_resp.get("hits", []) if stories_resp else []

    return comments, stories


async def _parallel_get(
    client: httpx.AsyncClient, *urls: str
) -> list[dict | None]:
    """GET multiple URLs concurrently, returning parsed JSON or None on failure."""
    import asyncio

    async def _get(url: str) -> dict | None:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return None

    return list(await asyncio.gather(*[_get(u) for u in urls]))


def _format_hn_evidence(
    username: str, comments: list[dict], stories: list[dict]
) -> str:
    """Format HN data into structured evidence text for LLM analysis."""
    sections: list[str] = []

    if stories:
        sections.append(_format_stories(stories))

    if comments:
        conflict, routine = _partition_comments(comments)
        if conflict:
            sections.append(
                _format_comments(
                    conflict,
                    header="HackerNews Comments -- CONFLICT & OPINION",
                    preamble=(
                        "[HIGHEST SIGNAL] These comments contain disagreement, pushback, "
                        "or strong opinions expressed in public technical discussions. "
                        "They reveal the person's true values, communication style, and "
                        "how they engage in debate."
                    ),
                )
            )
        if routine:
            sections.append(
                _format_comments(
                    routine,
                    header="HackerNews Comments -- General Discussion",
                    preamble=(
                        "General HN comments showing everyday communication style, "
                        "technical interests, and how the person participates in "
                        "community discussions."
                    ),
                )
            )

    if not sections:
        return (
            f"## HackerNews Activity\n"
            f"No public HackerNews activity found for user '{username}'."
        )

    intro = (
        "## HackerNews Activity\n"
        "(HN comments reveal unfiltered technical opinions, industry perspectives, "
        "and communication style in public technical discussions.)\n"
    )
    return intro + "\n\n".join(sections)


def _partition_comments(
    comments: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split comments into conflict/opinionated vs routine."""
    conflict = []
    routine = []
    for comment in comments:
        text = (comment.get("comment_text") or "").strip()
        if not text:
            continue
        if _CONFLICT_PATTERNS.search(text):
            conflict.append(comment)
        else:
            routine.append(comment)
    return conflict, routine


def _format_stories(stories: list[dict]) -> str:
    """Format story submissions."""
    lines = ["### Submitted Stories"]
    lines.append(
        "(Story submissions reveal what topics the person finds important "
        "enough to share with the community.)\n"
    )
    for story in stories[:30]:
        title = story.get("title") or "Untitled"
        points = story.get("points") or 0
        num_comments = story.get("num_comments") or 0
        url = story.get("url") or ""

        domain = ""
        if url:
            # Extract domain for context
            from urllib.parse import urlparse

            try:
                domain = f" ({urlparse(url).netloc})"
            except Exception:
                pass

        lines.append(f"- **{title}**{domain} [{points} points, {num_comments} comments]")
    return "\n".join(lines)


def _format_comments(
    comments: list[dict],
    header: str,
    preamble: str,
) -> str:
    """Format a list of HN comments with signal annotations."""
    lines = [f"### {header}"]
    lines.append(f"({preamble})\n")

    for comment in comments[:50]:
        text = (comment.get("comment_text") or "").strip()
        if not text:
            continue

        story_title = comment.get("story_title") or "Unknown Discussion"
        points = comment.get("points")
        created_at = comment.get("created_at", "")

        # Detect signal markers
        tags = []
        if _CONFLICT_PATTERNS.search(text):
            tags.append("CONFLICT/OPINION")
        if _STRONG_EMOTION_PATTERNS.search(text):
            emotion_matches = _STRONG_EMOTION_PATTERNS.findall(text)
            tags.append(f"STRONG EMOTION: {', '.join(emotion_matches[:3])}")

        tag_str = f" [{'; '.join(tags)}]" if tags else ""
        points_str = f" [{points} points]" if points else ""

        # Strip HTML tags from comment text (HN API returns HTML)
        clean_text = _strip_html(text)
        if len(clean_text) > 600:
            clean_text = clean_text[:600] + "..."

        lines.append(f"**On: \"{story_title}\"**{tag_str}{points_str}")
        lines.append(f"> \"{clean_text}\"")
        lines.append("")

    return "\n".join(lines)


def _strip_html(text: str) -> str:
    """Remove HTML tags from HN comment text."""
    # Replace common HTML entities and tags
    text = text.replace("<p>", "\n\n").replace("</p>", "")
    text = text.replace("<i>", "_").replace("</i>", "_")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<code>", "`").replace("</code>", "`")
    text = text.replace("<pre>", "```\n").replace("</pre>", "\n```")
    text = text.replace("&gt;", ">").replace("&lt;", "<")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    text = text.replace("&#x27;", "'").replace("&#x2F;", "/")
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
