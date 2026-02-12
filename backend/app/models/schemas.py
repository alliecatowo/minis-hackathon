from __future__ import annotations

import datetime
import json
from typing import Any

from pydantic import BaseModel, model_validator


# -- Request schemas --

class CreateMiniRequest(BaseModel):
    username: str
    sources: list[str] = ["github"]  # Ingestion sources to use
    excluded_repos: list[str] = []  # Repo full names to exclude


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    context: str | None = None  # Communication context key (e.g. "code_review")


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


# -- Response schemas --

class MiniSummary(BaseModel):
    id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    owner_id: int | None = None
    visibility: str = "public"
    status: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class MiniDetailValue(BaseModel):
    name: str
    description: str
    intensity: float


class MiniDetail(BaseModel):
    id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    owner_id: int | None = None
    visibility: str = "public"
    org_id: int | None = None
    bio: str | None
    spirit_content: str | None
    memory_content: str | None = None
    system_prompt: str | None
    values_json: str | None = None
    roles_json: str | None = None
    skills_json: str | None = None
    traits_json: str | None = None
    metadata_json: str | None = None
    sources_used: str | None = None
    values: list[MiniDetailValue] = []
    roles: dict = {}
    skills: list[str] = []
    traits: list[str] = []
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def parse_values(self) -> MiniDetail:
        if self.values_json:
            try:
                data = json.loads(self.values_json)
                eng_values = data.get("engineering_values", [])
                self.values = [
                    MiniDetailValue(
                        name=v.get("name", ""),
                        description=v.get("description", ""),
                        intensity=v.get("intensity", 0.5),
                    )
                    for v in eng_values
                ]
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        if self.roles_json:
            try:
                self.roles = json.loads(self.roles_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if self.skills_json:
            try:
                self.skills = json.loads(self.skills_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if self.traits_json:
            try:
                self.traits = json.loads(self.traits_json)
            except (json.JSONDecodeError, TypeError):
                pass
        return self


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


class DecisionPattern(BaseModel):
    """A recurring decision pattern: When faced with X, this person chooses Y because Z."""
    trigger: str  # The situation or stimulus
    response: str  # What they consistently do
    reasoning: str  # Why they make this choice
    evidence: list[str]  # Quotes or examples showing this pattern


class ConflictInstance(BaseModel):
    """A specific moment where the developer pushed back, disagreed, or defended a position."""
    category: str  # "technical_disagreement", "style_preference", "process_pushback", "architecture_debate"
    summary: str  # What the conflict was about
    their_position: str  # What they argued for
    outcome: str  # How it resolved (conceded, compromised, held firm)
    quote: str  # Their actual words during the conflict
    revealed_value: str  # What this tells us about their values


class BehavioralExample(BaseModel):
    """A real quote from their GitHub activity with context, for few-shot prompting."""
    context: str  # e.g. "When reviewing a PR that lacked tests"
    quote: str  # Their actual words
    source_type: str  # "review_comment", "issue_comment", "pr_description", "commit_message"


class CommunicationStyle(BaseModel):
    tone: str
    formality: str
    emoji_usage: str
    catchphrases: list[str]
    feedback_style: str
    # Context-dependent communication patterns
    code_review_voice: str  # How they sound in code reviews specifically
    issue_discussion_voice: str  # How they sound in issue discussions
    casual_voice: str  # How they sound in informal contexts
    signature_phrases: list[str]  # Exact phrases they use verbatim, repeatedly


class PersonalityPattern(BaseModel):
    humor: str
    directness: str
    mentoring_style: str
    conflict_approach: str


class BehavioralBoundary(BaseModel):
    """Things this developer would NEVER say or do -- equally defining as what they do."""
    never_says: list[str]  # Phrases, tones, or patterns they avoid
    never_does: list[str]  # Behaviors or approaches they reject
    pet_peeves: list[str]  # Things that visibly annoy or frustrate them
    anti_values: list[str]  # Engineering values they actively argue against


class TechnicalOpinion(BaseModel):
    topic: str
    opinion: str
    quote: str = ""


class TechnicalProfile(BaseModel):
    primary_languages: list[str] = []
    frameworks_and_tools: list[str] = []
    domains: list[str] = []
    technical_opinions: list[TechnicalOpinion] = []
    projects_summary: str = ""


class ExtractedValues(BaseModel):
    engineering_values: list[EngineeringValue]
    decision_patterns: list[DecisionPattern]
    conflict_instances: list[ConflictInstance]
    behavioral_examples: list[BehavioralExample]
    communication_style: CommunicationStyle
    personality_patterns: PersonalityPattern
    behavioral_boundaries: BehavioralBoundary
    technical_profile: TechnicalProfile = TechnicalProfile()
