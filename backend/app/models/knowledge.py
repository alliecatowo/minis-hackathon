"""Models for the Knowledge Graph and Principles Matrix."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    SKILL = "skill"
    PROJECT = "project"
    CONCEPT = "concept"
    PATTERN = "pattern"
    ARCHITECTURE = "architecture"
    FRAMEWORK = "framework"
    LANGUAGE = "language"
    LIBRARY = "library"
    OTHER = "other"


class RelationType(str, Enum):
    USED_IN = "used_in"
    BUILT_WITH = "built_with"
    LOVES = "loves"
    HATES = "hates"
    EXPERT_IN = "expert_in"
    BEGINNER_IN = "beginner_in"
    CONTRIBUTED_TO = "contributed_to"
    RELATED_TO = "related_to"


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph representing a specific entity."""

    id: str = Field(
        description="Unique identifier for the node, typically name-lowercase"
    )
    name: str = Field(description="Display name of the node")
    type: NodeType = Field(description="Type of the knowledge node")
    depth: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Proficiency or depth of knowledge (0.0-1.0)",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in this knowledge assessment",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Links to specific diffs, files, or commits",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class KnowledgeEdge(BaseModel):
    """A directed edge representing a relationship between two knowledge nodes."""

    source: str = Field(description="ID of the source node")
    target: str = Field(description="ID of the target node")
    relation: RelationType = Field(description="Type of relationship")
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Strength of the relationship",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Links to specific diffs, files, or commits",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class KnowledgeGraph(BaseModel):
    """Container for the knowledge graph."""

    nodes: list[KnowledgeNode] = Field(default_factory=list)
    edges: list[KnowledgeEdge] = Field(default_factory=list)


class Principle(BaseModel):
    """A guiding principle for decision making."""

    trigger: str = Field(
        description="The situation that triggers this principle (e.g., 'Junior dev adds a library')"
    )
    action: str = Field(description="The action taken in response (e.g., 'Reject')")
    value: str = Field(
        description="The underlying value (e.g., 'Dependency Minimalism')"
    )
    intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How strongly this principle is held",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Links to specific diffs, files, or commits",
    )


class PrinciplesMatrix(BaseModel):
    """Container for the principles matrix."""

    principles: list[Principle] = Field(default_factory=list)
