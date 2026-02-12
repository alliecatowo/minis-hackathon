"""Blog/RSS ingestion source plugin.

Fetches and parses blog posts from RSS/Atom feeds for personality analysis.
Blog posts are rich sources of writing style, technical opinions, and
in-depth thinking that complement shorter-form GitHub activity.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin

import httpx

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

# Common feed paths to probe when given a bare URL
_FEED_PATHS = ("/feed", "/rss", "/atom.xml", "/feed.xml", "/rss.xml", "/index.xml")

# HTML tag stripping regex
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Namespace prefixes commonly found in Atom/RSS feeds
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"

# Max content length per post (characters) to keep evidence manageable
_MAX_POST_CONTENT = 4000
_MAX_POSTS = 50


class BlogSource(IngestionSource):
    """Ingestion source that fetches blog/RSS content for personality analysis."""

    name = "blog"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch blog posts from an RSS/Atom feed URL.

        Args:
            identifier: A blog URL or direct RSS/Atom feed URL.
            **config: Optional overrides.
                max_posts: Maximum posts to process (default 50).
                timeout: HTTP request timeout in seconds (default 15).
        """
        max_posts = config.get("max_posts", _MAX_POSTS)
        timeout = config.get("timeout", 15)

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Minis/1.0 (blog ingestion)"},
        ) as client:
            feed_url, feed_xml = await _resolve_feed(client, identifier)

        if not feed_xml:
            return IngestionResult(
                source_name=self.name,
                identifier=identifier,
                evidence="",
                raw_data={"error": "Could not find or fetch RSS/Atom feed"},
                stats={"post_count": 0},
            )

        posts = _parse_feed(feed_xml, max_posts=max_posts)
        evidence = _format_evidence(posts)
        total_words = sum(p.get("word_count", 0) for p in posts)

        date_range = ""
        dates = [p["date"] for p in posts if p.get("date")]
        if dates:
            date_range = f"{dates[-1]} to {dates[0]}"

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "feed_url": feed_url,
                "posts": [
                    {
                        "title": p.get("title", ""),
                        "date": p.get("date", ""),
                        "tags": p.get("tags", []),
                    }
                    for p in posts
                ],
            },
            stats={
                "post_count": len(posts),
                "total_word_count": total_words,
                "date_range": date_range,
                "tags_found": list(
                    {tag for p in posts for tag in p.get("tags", [])}
                ),
                "evidence_length": len(evidence),
            },
        )


# ---------------------------------------------------------------------------
# Feed Discovery
# ---------------------------------------------------------------------------


async def _resolve_feed(
    client: httpx.AsyncClient, url: str
) -> tuple[str, str | None]:
    """Try to get RSS/Atom XML from a URL.

    First tries the URL directly (it might already be a feed). If that
    returns HTML, looks for <link rel="alternate"> feed references, then
    probes common feed paths.

    Returns (feed_url, xml_text) or (url, None) on failure.
    """
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Try the URL directly
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.text
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return url, None

    # Check if this is already XML (feed)
    if _looks_like_feed(body):
        return url, body

    # It's HTML — look for feed link tags
    feed_url = _find_feed_link(body, url)
    if feed_url:
        try:
            resp = await client.get(feed_url)
            resp.raise_for_status()
            if _looks_like_feed(resp.text):
                return feed_url, resp.text
        except httpx.HTTPError:
            pass

    # Probe common feed paths
    for path in _FEED_PATHS:
        probe_url = urljoin(url.rstrip("/") + "/", path.lstrip("/"))
        try:
            resp = await client.get(probe_url)
            if resp.status_code == 200 and _looks_like_feed(resp.text):
                return probe_url, resp.text
        except httpx.HTTPError:
            continue

    logger.warning("No feed found for %s", url)
    return url, None


def _looks_like_feed(text: str) -> bool:
    """Heuristic check: does this text look like an RSS/Atom feed?"""
    stripped = text.lstrip()[:500]
    return (
        stripped.startswith("<?xml")
        or "<rss" in stripped
        or "<feed" in stripped
        or "<channel>" in stripped
    )


def _find_feed_link(html: str, base_url: str) -> str | None:
    """Extract RSS/Atom feed URL from HTML <link> tags."""
    # Match <link rel="alternate" type="application/rss+xml" href="...">
    # and <link rel="alternate" type="application/atom+xml" href="...">
    pattern = re.compile(
        r'<link\s[^>]*rel=["\']alternate["\'][^>]*'
        r'type=["\']application/(?:rss|atom)\+xml["\'][^>]*'
        r'href=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        # Try reversed attribute order (type before rel)
        pattern2 = re.compile(
            r'<link\s[^>]*type=["\']application/(?:rss|atom)\+xml["\'][^>]*'
            r'rel=["\']alternate["\'][^>]*'
            r'href=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        match = pattern2.search(html)

    if match:
        href = match.group(1)
        return urljoin(base_url, href)

    return None


# ---------------------------------------------------------------------------
# Feed Parsing
# ---------------------------------------------------------------------------


def _parse_feed(xml_text: str, *, max_posts: int = _MAX_POSTS) -> list[dict[str, Any]]:
    """Parse RSS or Atom XML into a list of post dicts.

    Each post dict has: title, date, content, tags, word_count, link.
    Posts are sorted newest-first.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("Failed to parse feed XML: %s", exc)
        return []

    # Determine feed type and parse accordingly
    tag = root.tag.lower().split("}")[-1] if "}" in root.tag else root.tag.lower()

    if tag == "feed":
        posts = _parse_atom(root)
    elif tag == "rss":
        posts = _parse_rss(root)
    else:
        # Try to find channel/item elements anyway
        posts = _parse_rss(root)

    # Sort newest-first and cap
    posts.sort(key=lambda p: p.get("date", ""), reverse=True)
    return posts[:max_posts]


def _parse_rss(root: ET.Element) -> list[dict[str, Any]]:
    """Parse RSS 2.0 feed items."""
    posts: list[dict[str, Any]] = []

    for item in root.iter("item"):
        title = _text(item, "title")
        link = _text(item, "link")
        pub_date = _text(item, "pubDate")
        date = _normalize_date(pub_date)

        # Content: prefer content:encoded, fall back to description
        content = _text(item, f"{_CONTENT_NS}encoded") or _text(item, "description")
        content = _strip_html(content)

        # Tags/categories
        tags = [cat.text.strip() for cat in item.findall("category") if cat.text]

        # Author
        author = _text(item, f"{_DC_NS}creator") or _text(item, "author")

        word_count = len(content.split()) if content else 0

        posts.append({
            "title": title,
            "date": date,
            "content": content[:_MAX_POST_CONTENT] if content else "",
            "tags": tags,
            "link": link,
            "author": author,
            "word_count": word_count,
        })

    return posts


def _parse_atom(root: ET.Element) -> list[dict[str, Any]]:
    """Parse Atom feed entries."""
    posts: list[dict[str, Any]] = []

    for entry in root.iter(f"{_ATOM_NS}entry"):
        title = _text(entry, f"{_ATOM_NS}title")
        link_el = entry.find(f"{_ATOM_NS}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{_ATOM_NS}link")
        link = link_el.get("href", "") if link_el is not None else ""

        updated = _text(entry, f"{_ATOM_NS}updated") or _text(entry, f"{_ATOM_NS}published")
        date = _normalize_date(updated)

        # Content: prefer content element, fall back to summary
        content = _text(entry, f"{_ATOM_NS}content") or _text(entry, f"{_ATOM_NS}summary")
        content = _strip_html(content)

        # Tags/categories
        tags = [
            cat.get("term", "").strip()
            for cat in entry.findall(f"{_ATOM_NS}category")
            if cat.get("term")
        ]

        author_el = entry.find(f"{_ATOM_NS}author")
        author = ""
        if author_el is not None:
            author = _text(author_el, f"{_ATOM_NS}name")

        word_count = len(content.split()) if content else 0

        posts.append({
            "title": title,
            "date": date,
            "content": content[:_MAX_POST_CONTENT] if content else "",
            "tags": tags,
            "link": link,
            "author": author,
            "word_count": word_count,
        })

    return posts


def _text(element: ET.Element, tag: str) -> str:
    """Safely extract text from a child element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    if not text:
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", text)
    cleaned = unescape(cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_date(date_str: str) -> str:
    """Try to parse various date formats into YYYY-MM-DD."""
    if not date_str:
        return ""

    # Try ISO 8601 formats first
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # RFC 2822 (common in RSS pubDate)
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(date_str).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass

    return date_str.strip()[:10]  # Best-effort truncation


# ---------------------------------------------------------------------------
# Evidence Formatting
# ---------------------------------------------------------------------------


def _format_evidence(posts: list[dict[str, Any]]) -> str:
    """Format blog posts into evidence text for LLM personality analysis."""
    if not posts:
        return ""

    sections: list[str] = [
        "## Blog Posts (Personal Writing)\n"
        "(Blog posts reveal in-depth opinions, technical knowledge, and writing style "
        "that may not appear in shorter-form GitHub activity.)\n"
    ]

    for post in posts:
        title = post.get("title", "Untitled")
        date = post.get("date", "")
        content = post.get("content", "")
        tags = post.get("tags", [])

        date_str = f" ({date})" if date else ""
        sections.append(f'### "{title}"{date_str}')

        if content:
            # Extract a representative excerpt showing personality/opinion
            excerpt = _extract_excerpt(content)
            if excerpt:
                sections.append(f'> "{excerpt}"')

        if tags:
            tag_str = ", ".join(tags[:10])
            sections.append(f"[Tags: {tag_str}]")

        sections.append("")

    return "\n".join(sections)


def _extract_excerpt(content: str, max_len: int = 500) -> str:
    """Extract a representative excerpt from post content.

    Prefers sentences that contain opinion/personality markers.
    Falls back to the opening of the content.
    """
    # Split into sentences (rough)
    sentences = re.split(r"(?<=[.!?])\s+", content)

    # Look for sentences with opinion/personality signals
    opinion_markers = re.compile(
        r"\b(I think|I believe|I prefer|I've found|in my experience|"
        r"the problem with|what I learned|my approach|"
        r"should|shouldn't|important|better|worse|"
        r"love|hate|annoying|amazing|terrible|great)\b",
        re.IGNORECASE,
    )

    personality_sentences = [s for s in sentences if opinion_markers.search(s)]
    if personality_sentences:
        excerpt = " ".join(personality_sentences)[:max_len]
    else:
        # Fall back to the beginning of the content
        excerpt = content[:max_len]

    if len(excerpt) < len(content):
        excerpt = excerpt.rsplit(" ", 1)[0] + "..."

    return excerpt
