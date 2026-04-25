"""Models for evidence storage and explorer progress tracking.

Evidence represents raw data from ingestion sources. ExplorerFinding and
ExplorerQuote capture structured outputs from explorer agents.
ExplorerProgress tracks per-source agent progress for a mini.
"""

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class Evidence(Base):
    """Raw data from ingestion sources, organized per mini per source."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(String(64), nullable=False, default="general", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_privacy: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    retention_policy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retention_expires_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_authorization: Mapped[str | None] = mapped_column(String(32), nullable=True)
    authorization_revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_classification: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    lifecycle_audit_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audience_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_body_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explored: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Incremental ingestion fields (ALLIE-374 M1)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    evidence_date: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_fetched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # AI contamination detection (ALLIE-444) — 0.0 = authentic, 1.0 = AI-generated; NULL = unscored
    ai_contamination_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_contamination_checked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Partial unique index: prevents duplicate inserts for the same
        # (mini, source, external_id) tuple. NULL external_id is excluded
        # so legacy rows (no external_id) don't conflict with each other.
        Index(
            "uq_evidence_mini_source_external_id",
            "mini_id",
            "source_type",
            "external_id",
            unique=True,
            postgresql_where="external_id IS NOT NULL",
        ),
    )

    def provenance_envelope(self) -> dict[str, object]:
        """Return the review-grade provenance envelope for this evidence row.

        Missing values are intentionally represented as ``None`` so callers do
        not infer fake provenance for legacy or sparse evidence.
        """
        return {
            "evidence_id": self.id,
            "subject_id": self.mini_id,
            "source_type": self.source_type,
            "item_type": self.item_type,
            "external_id": self.external_id,
            "source_uri": self.source_uri,
            "scope": self.scope_json,
            "timestamp": self.evidence_date,
            "ingested_at": self.created_at,
            "last_fetched_at": self.last_fetched_at,
            "author_id": self.author_id,
            "audience_id": self.audience_id,
            "target_id": self.target_id,
            "visibility": self.source_privacy,
            "retention_policy": self.retention_policy,
            "retention_expires_at": self.retention_expires_at,
            "source_authorization": self.source_authorization,
            "authorization_revoked_at": self.authorization_revoked_at,
            "access_classification": self.access_classification,
            "lifecycle_audit": self.lifecycle_audit_json,
            "content_hash": self.content_hash,
            "raw_excerpt": self.raw_body if self.raw_body is not None else self.content,
            "raw_body_ref": self.raw_body_ref,
            "surrounding_context_ref": (
                self.raw_context_json.get("ref")
                if isinstance(self.raw_context_json, dict)
                else None
            ),
            "raw_context": self.raw_context_json,
            "ai_contamination_confidence": self.ai_contamination_score,
            "provenance": self.provenance_json,
            "provenance_confidence": (
                self.provenance_json.get("confidence")
                if isinstance(self.provenance_json, dict)
                else None
            ),
        }


class ExplorerFinding(Base):
    """Structured findings persisted by explorer agents."""

    __tablename__ = "explorer_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExplorerQuote(Base):
    """Behavioral quotes extracted by explorer agents."""

    __tablename__ = "explorer_quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    significance: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ExplorerProgress(Base):
    """Tracks agent progress per mini per source."""

    __tablename__ = "explorer_progress"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    explored_items: Mapped[int] = mapped_column(Integer, default=0)
    findings_count: Mapped[int] = mapped_column(Integer, default=0)
    memories_count: Mapped[int] = mapped_column(Integer, default=0)
    quotes_count: Mapped[int] = mapped_column(Integer, default=0)
    nodes_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    started_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Incremental ingestion: timestamp of the most recent successful exploration (ALLIE-374 M1)
    last_explored_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReviewCycle(Base):
    """Durable review prediction/outcome cycle for closed-loop learning."""

    __tablename__ = "review_cycles"
    __table_args__ = (
        UniqueConstraint(
            "mini_id",
            "source_type",
            "external_id",
            name="uq_review_cycles_mini_source_external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="github", index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    predicted_state: Mapped[dict] = mapped_column("predicted_state_json", JSON, nullable=False)
    human_review_outcome: Mapped[dict | None] = mapped_column(
        "human_review_outcome_json", JSON, nullable=True
    )
    delta_metrics: Mapped[dict | None] = mapped_column("delta_metrics_json", JSON, nullable=True)
    predicted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    human_reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ArtifactReviewCycle(Base):
    """Durable artifact-review (design_doc / issue_plan) prediction/outcome cycle."""

    __tablename__ = "artifact_review_cycles"
    __table_args__ = (
        UniqueConstraint(
            "mini_id",
            "artifact_type",
            "external_id",
            name="uq_artifact_review_cycles_mini_type_external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # "design_doc" | "issue_plan"
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Full ArtifactReviewV1 blob
    predicted_state: Mapped[dict] = mapped_column("predicted_state_json", JSON, nullable=False)
    # ArtifactReviewOutcomeCaptureV1 blob
    human_outcome: Mapped[dict | None] = mapped_column("human_outcome_json", JSON, nullable=True)
    delta_metrics: Mapped[dict | None] = mapped_column("delta_metrics_json", JSON, nullable=True)
    predicted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finalized_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
