import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Mini(Base):
    __tablename__ = "minis"
    __table_args__ = (UniqueConstraint("owner_id", "username", name="uq_mini_owner_username"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), index=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    org_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    bio: Mapped[str | None] = mapped_column(Text)

    spirit_content: Mapped[str | None] = mapped_column(Text)
    memory_content: Mapped[str | None] = mapped_column(Text)  # Factual knowledge bank
    system_prompt: Mapped[str | None] = mapped_column(Text)
    values_json: Mapped[str | None] = mapped_column(Text)
    roles_json: Mapped[str | None] = mapped_column(Text)
    skills_json: Mapped[str | None] = mapped_column(Text)
    traits_json: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    sources_used: Mapped[str | None] = mapped_column(Text)  # JSON list of source names
    evidence_cache: Mapped[str | None] = mapped_column(Text)  # Concatenated evidence for chat tools

    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
