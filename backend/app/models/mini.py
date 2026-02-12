import datetime
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Mini(Base):
    """A developer personality clone (engram).

    Naming conventions:
        spirit_content  -- "spirit" / "soul document": the personality engram text
                           used as the system prompt for the AI clone. Written in
                           second person, it defines voice, values, and behavior.
        memory_content  -- Factual knowledge bank assembled from explorer reports.
                           Merged memories across all sources (projects, expertise,
                           opinions, etc.).
        values_json     -- Radar chart data: 8-axis trait scores used by the
                           frontend PersonalityRadar visualization.
        principles_json -- Behavioral decision matrix extracted by explorers.
                           Each entry is a trigger -> action pattern with an
                           underlying value and intensity score.
        knowledge_graph_json -- Structured node/edge graph of technical knowledge.
                           Nodes represent skills, projects, and concepts; edges
                           encode relationships (USED_IN, LOVES, HATES, etc.).
    """

    __tablename__ = "minis"
    __table_args__ = (
        UniqueConstraint("owner_id", "username", name="uq_mini_owner_username"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(255), index=True)
    owner_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    org_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    bio: Mapped[str | None] = mapped_column(Text)

    spirit_content: Mapped[str | None] = mapped_column(Text)
    memory_content: Mapped[str | None] = mapped_column(Text)  # Factual knowledge bank
    knowledge_graph_json: Mapped[dict | None] = mapped_column(
        JSON
    )  # Structured knowledge graph (nodes/edges)
    principles_json: Mapped[dict | None] = mapped_column(
        JSON
    )  # Structured principles matrix
    system_prompt: Mapped[str | None] = mapped_column(Text)
    values_json: Mapped[dict | None] = mapped_column(JSON)
    roles_json: Mapped[dict | None] = mapped_column(JSON)
    skills_json: Mapped[dict | None] = mapped_column(JSON)
    traits_json: Mapped[dict | None] = mapped_column(JSON)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    sources_used: Mapped[list | None] = mapped_column(JSON)  # JSON list of source names
    evidence_cache: Mapped[str | None] = mapped_column(
        Text
    )  # Concatenated evidence for chat tools

    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
