from __future__ import annotations

import datetime

from pydantic import BaseModel


# -- Request schemas --

class CreateMiniRequest(BaseModel):
    username: str
    sources: list[str] = ["github"]  # Ingestion sources to use


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


# -- Response schemas --

class MiniSummary(BaseModel):
    id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    status: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class MiniDetail(BaseModel):
    id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    bio: str | None
    spirit_content: str | None
    system_prompt: str | None
    values_json: str | None
    metadata_json: str | None
    sources_used: str | None
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class PipelineEvent(BaseModel):
    stage: str
    status: str  # "started", "completed", "failed"
    message: str
    progress: float  # 0.0 - 1.0


# -- Value extraction schemas --

class EngineeringValue(BaseModel):
    name: str
    description: str
    intensity: float  # 0.0 - 1.0
    evidence: list[str]


class CommunicationStyle(BaseModel):
    tone: str
    formality: str
    emoji_usage: str
    catchphrases: list[str]
    feedback_style: str


class PersonalityPattern(BaseModel):
    humor: str
    directness: str
    mentoring_style: str
    conflict_approach: str


class ExtractedValues(BaseModel):
    engineering_values: list[EngineeringValue]
    communication_style: CommunicationStyle
    personality_patterns: PersonalityPattern
