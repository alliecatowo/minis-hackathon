"""Website ingestion source plugin.

Fetches and extracts content from websites using trafilatura for personality
analysis. Unlike the blog source (RSS-only), this handles arbitrary websites
by crawling pages via sitemaps or internal link discovery.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from trafilatura.sitemaps import sitemap_search

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

# Limits
_MAX_PAGES = 50
_MAX_CONTENT_PER_PAGE = 4000


class WebsiteSource(IngestionSource):
    """Ingestion source that scrapes website content for personality analysis."""

    name = "website"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch website pages and extract clean text content.

        Args:
            identifier: A website URL to scrape.
            **config: Optional overrides.
                max_pages: Maximum pages to process (default 50).
                timeout: HTTP request timeout in seconds (default 15).
        """
        max_pages = config.get("max_pages", _MAX_PAGES)
        timeout = config.get("timeout", 15)

        url = identifier.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Minis/1.0 (website ingestion)"},
        ) as client:
            page_urls = await _discover_pages(client, url, max_pages)

        if not page_urls:
            return IngestionResult(
                source_name=self.name,
                identifier=identifier,
                evidence="",
                raw_data={"error": "Could not discover any pages"},
                stats={"page_count": 0},
            )

        pages = _extract_pages(page_urls)
        evidence = _format_evidence(pages)
        total_words = sum(p.get("word_count", 0) for p in pages)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "base_url": url,
                "pages": [
                    {
                        "title": p.get("title", ""),
                        "url": p.get("url", ""),
                    }
                    for p in pages
                ],
            },
            stats={
                "page_count": len(pages),
                "total_word_count": total_words,
                "evidence_length": len(evidence),
            },
        )


# ---------------------------------------------------------------------------
# Page Discovery
# ---------------------------------------------------------------------------


async def _discover_pages(
    client: httpx.AsyncClient, url: str, max_pages: int
) -> list[str]:
    """Discover page URLs from a website.

    Strategy:
    1. Try sitemap discovery via trafilatura
    2. Fall back to parsing internal links from the main page
    """
    base_domain = urlparse(url).netloc

    # Try sitemap-based discovery
    try:
        sitemap_urls = sitemap_search(url)
        if sitemap_urls:
            # Filter to same domain
            same_domain = [
                u for u in sitemap_urls if urlparse(u).netloc == base_domain
            ]
            if same_domain:
                logger.info(
                    "Found %d pages via sitemap for %s", len(same_domain), url
                )
                return same_domain[:max_pages]
    except Exception as exc:
        logger.debug("Sitemap discovery failed for %s: %s", url, exc)

    # Fall back to internal link parsing from the main page
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return []

    internal_links = _extract_internal_links(html, url, base_domain)

    # Always include the main page first
    page_urls = [url]
    seen = {url, url.rstrip("/")}
    for link in internal_links:
        normalized = link.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            page_urls.append(link)
        if len(page_urls) >= max_pages:
            break

    logger.info(
        "Discovered %d pages via link parsing for %s", len(page_urls), url
    )
    return page_urls


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# Skip common non-content paths
_SKIP_PATTERNS = re.compile(
    r"(/wp-admin|/wp-content|/wp-includes|/tag/|/category/"
    r"|/page/\d|#|\.(css|js|png|jpg|jpeg|gif|svg|ico|pdf|zip|woff|ttf)$)",
    re.IGNORECASE,
)


def _extract_internal_links(html: str, base_url: str, base_domain: str) -> list[str]:
    """Extract same-domain links from HTML."""
    links: list[str] = []

    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue

        # Resolve relative URLs
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Only same-domain, HTTP(S) links
        if parsed.netloc != base_domain:
            continue
        if parsed.scheme not in ("http", "https"):
            continue
        if _SKIP_PATTERNS.search(full_url):
            continue

        # Strip fragments and query params for deduplication
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        links.append(clean_url)

    return links


# ---------------------------------------------------------------------------
# Content Extraction
# ---------------------------------------------------------------------------


def _extract_pages(urls: list[str]) -> list[dict[str, Any]]:
    """Extract text content from a list of URLs using trafilatura."""
    pages: list[dict[str, Any]] = []

    for url in urls:
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                continue

            content = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
            )
            if not content or len(content.strip()) < 50:
                continue

            # Extract metadata separately
            metadata = trafilatura.extract(
                downloaded,
                output_format="json",
                include_comments=False,
            )
            title = ""
            if metadata:
                import json

                try:
                    meta_dict = json.loads(metadata)
                    title = meta_dict.get("title", "")
                except (json.JSONDecodeError, TypeError):
                    # Invalid metadata JSON, use default title
                    pass

            content = content[:_MAX_CONTENT_PER_PAGE]
            word_count = len(content.split())

            pages.append({
                "title": title or _title_from_url(url),
                "url": url,
                "content": content,
                "word_count": word_count,
            })
        except Exception as exc:
            logger.debug("Failed to extract %s: %s", url, exc)
            continue

    return pages


def _title_from_url(url: str) -> str:
    """Generate a fallback title from a URL path."""
    path = urlparse(url).path.strip("/")
    if not path:
        return "Home"
    # Take the last segment, replace hyphens/underscores with spaces
    segment = path.split("/")[-1]
    segment = segment.replace("-", " ").replace("_", " ")
    return segment.title()


# ---------------------------------------------------------------------------
# Evidence Formatting
# ---------------------------------------------------------------------------


def _format_evidence(pages: list[dict[str, Any]]) -> str:
    """Format extracted website pages into evidence text for LLM analysis."""
    if not pages:
        return ""

    sections: list[str] = [
        "## Website Pages (Personal/Project Content)\n"
        "(Website content reveals how a developer presents themselves, "
        "their projects, values, and communication style.)\n"
    ]

    for page in pages:
        title = page.get("title", "Untitled")
        url = page.get("url", "")
        content = page.get("content", "")

        sections.append(f"### {title}")
        if url:
            sections.append(f"URL: {url}")

        if content:
            sections.append(content)

        sections.append("")

    return "\n".join(sections)
