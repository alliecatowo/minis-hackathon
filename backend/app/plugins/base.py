"""Base protocols for the Minis plugin system.

Ingestion sources fetch structured evidence items from external services and
store them in the database for the LLM synthesis pipeline. Client plugins
expose a mini through different interfaces (web, MCP, CLI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeAlias

EvidenceContext: TypeAlias = Literal[
    "general",
    "code_review",
    "issue_discussion",
    "commit_message",
    "private_chat",
    "blog_post",
    "website_page",
    "hackernews_comment",
    "hackernews_story",
    "stackoverflow_answer",
    "devto_article",
]


@dataclass
class IngestionResult:
    """Standard output from an ingestion source.

    Used to carry profile metadata (raw_data) and stats back to the pipeline
    after the structured fetch_items() pass completes.
    """

    source_name: str
    identifier: str  # e.g. GitHub username, file path, Slack workspace
    evidence: str  # Combined evidence text for evidence_cache (explorer context)
    raw_data: dict[str, Any] = field(default_factory=dict)  # Preserved for metadata
    stats: dict[str, Any] = field(default_factory=dict)  # Source-specific stats


@dataclass
class EvidenceItem:
    """Structured evidence item emitted by a source's fetch_items() method.

    Each item carries a stable external_id that enables idempotent upserts and
    incremental re-fetch — only new or mutated items need to be processed on
    subsequent pipeline runs.

    external_id formats (by source):
      - GitHub commits:        ``commit:{sha}``
      - GitHub PRs:            ``pr:{owner}/{repo}#{number}``
      - GitHub reviews:        ``review:{pr_id}#{review_id}``
      - GitHub issue comments: ``issue_comment:{id}``
      - Claude Code turns:     ``session:{session_uuid}#{turn_idx}``

    context values are intentionally bounded so downstream synthesis can rely
    on a stable taxonomy instead of inferring source-specific meaning from
    free-form metadata.

    Envelope fields are nullable on purpose: sources should populate only what
    they actually know.  Missing author/audience/scope/provenance must remain
    explicit instead of being replaced by generic fake defaults.
    """

    external_id: str  # Stable identifier; unique within (mini_id, source_type)
    source_type: str  # Matches existing free-text source_type on Evidence rows
    item_type: str  # e.g. "commit", "pr", "review", "session"
    content: str
    context: EvidenceContext = "general"
    evidence_date: datetime | None = None
    source_uri: str | None = None
    author_id: str | None = None
    audience_id: str | None = None
    target_id: str | None = None
    scope: dict[str, Any] | None = None
    raw_body: str | None = None
    raw_body_ref: str | None = None
    raw_context: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    retention_policy: str = "standard"
    retention_expires_at: datetime | None = None
    source_authorization: str = "authorized"
    authorization_revoked_at: datetime | None = None
    access_classification: Literal["public", "company", "private"] | None = None
    lifecycle_audit: dict[str, Any] | None = None
    metadata: dict | None = None
    privacy: Literal["public", "private"] = "public"


class IngestionSource(ABC):
    """Protocol for data ingestion sources.

    Each source knows how to fetch raw data from an external service and
    yield it as structured EvidenceItem objects for incremental ingestion.
    """

    name: str  # Unique identifier, e.g. "github", "claude_code", "slack"
    source_type: str = "voice"  # "voice" or "memory"
    default_privacy: Literal["public", "private"] = "public"

    @abstractmethod
    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncGenerator[EvidenceItem, None]:
        """Yield structured EvidenceItem objects for this source.

        Each item carries a stable ``external_id`` to enable incremental
        ingestion — only new or mutated items are processed on subsequent
        pipeline runs.

        Args:
            identifier: Source-specific identifier (username, path, etc.).
            mini_id: The mini being built.
            session: Active async SQLAlchemy session (may be None in tests).
            since_external_ids: Set of external_ids already stored for this
                mini+source.  Sources should skip items whose external_id is
                already present (no-change fast path).

        Yields:
            EvidenceItem objects ready to be upserted into the Evidence table.
        """
        # Abstract body — subclasses must implement via `async def` + `yield`.
        raise NotImplementedError
        yield  # noqa: RET508 — makes this an async generator for type-checkers


class ClientPlugin(ABC):
    """Protocol for output client plugins.

    Each client exposes a mini's personality through a different interface.
    Clients are registered at startup and may add routes, start servers, etc.
    """

    name: str  # Unique identifier, e.g. "web", "mcp", "cli"

    @abstractmethod
    async def setup(self, app: Any) -> None:
        """Initialize the client plugin. Called during app startup.

        Args:
            app: The FastAPI application instance (or None for standalone clients).
        """
        ...
