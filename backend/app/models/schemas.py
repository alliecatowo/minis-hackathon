from __future__ import annotations

import datetime
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


def _parse_json_value(value: Any) -> Any:
    """Parse a value that may be a JSON string or already-decoded dict/list."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


# -- Request schemas --


class CreateMiniRequest(BaseModel):
    username: str = Field(max_length=39)
    sources: list[str] = ["github"]  # Ingestion sources to use
    excluded_repos: list[str] = []  # Repo full names to exclude
    source_identifiers: dict[str, str] = {}  # Per-source identifiers (e.g. {"hackernews": "pg"})

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$", v):
            raise ValueError("Invalid GitHub username format")
        return v.strip()


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"] = Field(max_length=20)
    content: str = Field(max_length=50000)


class ChatRequest(BaseModel):
    message: str = Field(max_length=10000)
    history: list[ChatMessage] = Field(default=[], max_length=50)
    conversation_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def validate_total_size(self) -> "ChatRequest":
        total = len(self.message) + sum(len(m.content) for m in self.history)
        if total > 500_000:
            raise ValueError("Total message content too large")
        return self


class ReviewPredictionRequestV1(BaseModel):
    repo_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    diff_summary: str | None = Field(default=None, max_length=50000)
    changed_files: list[str] = Field(default_factory=list, max_length=200)
    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"] = "unknown"
    delivery_context: Literal["hotfix", "normal", "exploratory", "incident"] = "normal"

    @model_validator(mode="after")
    def validate_has_review_input(self) -> "ReviewPredictionRequestV1":
        if any(
            [
                self.title and self.title.strip(),
                self.description and self.description.strip(),
                self.diff_summary and self.diff_summary.strip(),
                self.changed_files,
            ]
        ):
            return self
        raise ValueError(
            "Provide at least one of title, description, diff_summary, or changed_files"
        )


# -- Response schemas --


class MiniSummary(BaseModel):
    id: str
    username: str
    display_name: str | None
    avatar_url: str | None
    owner_id: str | None = None
    visibility: str = "public"
    status: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class MiniDetailValue(BaseModel):
    name: str
    description: str
    intensity: float


class TypologyDimension(BaseModel):
    name: str
    value: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PersonalityTypologyFramework(BaseModel):
    framework: str
    profile: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: str | None = None
    dimensions: list[TypologyDimension] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class PersonalityTypology(BaseModel):
    summary: str | None = None
    frameworks: list[PersonalityTypologyFramework] = Field(default_factory=list)


class BehavioralContextEntry(BaseModel):
    context: str
    summary: str
    behaviors: list[str] = Field(default_factory=list)
    communication_style: str | None = None
    decision_style: str | None = None
    motivators: list[str] = Field(default_factory=list)
    stressors: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class BehavioralContext(BaseModel):
    summary: str | None = None
    contexts: list[BehavioralContextEntry] = Field(default_factory=list)


# -- Motivations schemas (ALLIE-429) --


class Motivation(BaseModel):
    """A single inferred goal, value, or anti-goal."""

    value: str  # e.g. "craftsmanship", "autonomy"
    category: Literal["short_term_goal", "medium_term_goal", "terminal_value", "anti_goal"]
    evidence_ids: list[str] = Field(default_factory=list)  # 2-3 supporting Evidence.id strings
    confidence: float = Field(ge=0.0, le=1.0)


class MotivationChain(BaseModel):
    """Motivation → Framework → Behavior causal chain."""

    motivation: str  # e.g. "craftsmanship"
    implied_framework: str  # e.g. "always write tests before merging"
    observed_behavior: str  # e.g. "blocks PRs without tests"
    evidence_ids: list[str] = Field(default_factory=list)


class MotivationsProfile(BaseModel):
    """Full motivations profile inferred from explorer evidence."""

    motivations: list[Motivation] = Field(default_factory=list)
    motivation_chains: list[MotivationChain] = Field(default_factory=list)
    summary: str = ""  # brief natural-language sketch


class ReviewPredictionEvidenceV1(BaseModel):
    source: Literal[
        "behavioral_context",
        "motivations",
        "principles",
        "memory",
        "evidence",
        "input",
    ]
    detail: str


class ReviewPredictionSignalV1(BaseModel):
    key: str
    summary: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[ReviewPredictionEvidenceV1] = Field(default_factory=list)


class ReviewPredictionPrivateAssessmentV1(BaseModel):
    blocking_issues: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    non_blocking_issues: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    open_questions: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    positive_signals: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewPredictionDeliveryPolicyV1(BaseModel):
    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"]
    context: Literal["hotfix", "normal", "exploratory", "incident"]
    strictness: Literal["low", "medium", "high"]
    teaching_mode: bool
    shield_author_from_noise: bool
    rationale: str


class ReviewPredictionCommentV1(BaseModel):
    type: Literal["blocker", "note", "question", "praise"]
    disposition: Literal["request_changes", "comment", "approve"]
    issue_key: str | None = None
    summary: str
    rationale: str


class ReviewPredictionExpressedFeedbackV1(BaseModel):
    summary: str
    comments: list[ReviewPredictionCommentV1] = Field(default_factory=list)
    approval_state: Literal["approve", "comment", "request_changes", "uncertain"]


class ReviewPredictionV1(BaseModel):
    version: Literal["review_prediction_v1"] = "review_prediction_v1"
    reviewer_username: str
    repo_name: str | None = None
    private_assessment: ReviewPredictionPrivateAssessmentV1
    delivery_policy: ReviewPredictionDeliveryPolicyV1
    expressed_feedback: ReviewPredictionExpressedFeedbackV1


class MiniDetail(BaseModel):
    id: str
    username: str
    display_name: str | None
    avatar_url: str | None
    owner_id: str | None = None
    visibility: str = "public"
    org_id: str | None = None
    bio: str | None
    spirit_content: str | None
    memory_content: str | None = None
    personality_typology_json: PersonalityTypology | None = None
    behavioral_context_json: BehavioralContext | None = None
    motivations_json: MotivationsProfile | None = None
    system_prompt: str | None
    values_json: Any = None
    roles_json: Any = None
    skills_json: Any = None
    traits_json: Any = None
    metadata_json: Any = None
    sources_used: Any = None
    values: list[MiniDetailValue] = []
    roles: dict = {}
    skills: list[str] = []
    traits: list[str] = []
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @staticmethod
    def _parse_json(value: Any) -> Any:
        return _parse_json_value(value)

    @field_validator(
        "personality_typology_json", "behavioral_context_json", "motivations_json", mode="before"
    )
    @classmethod
    def parse_structured_json(cls, value: Any) -> Any:
        return _parse_json_value(value)

    @model_validator(mode="after")
    def parse_values(self) -> MiniDetail:
        if self.values_json:
            try:
                data = self._parse_json(self.values_json)
                if data:
                    eng_values = data.get("engineering_values", [])
                    self.values = [
                        MiniDetailValue(
                            name=v.get("name", ""),
                            description=v.get("description", ""),
                            intensity=v.get("intensity", 0.5),
                        )
                        for v in eng_values
                    ]
            except (KeyError, TypeError):
                # Invalid values structure, skip parsing
                pass
        if self.roles_json:
            parsed = self._parse_json(self.roles_json)
            if parsed:
                self.roles = parsed
        if self.skills_json:
            parsed = self._parse_json(self.skills_json)
            if parsed:
                self.skills = parsed
        if self.traits_json:
            parsed = self._parse_json(self.traits_json)
            if parsed:
                self.traits = parsed
        return self


class MiniPublic(BaseModel):
    """MiniDetail without sensitive fields (system_prompt, spirit_content, memory_content).

    Used for non-owner responses to prevent leaking the mini's internal prompts.
    """

    id: str
    username: str
    display_name: str | None
    avatar_url: str | None
    owner_id: str | None = None
    visibility: str = "public"
    org_id: str | None = None
    bio: str | None
    personality_typology_json: PersonalityTypology | None = None
    behavioral_context_json: BehavioralContext | None = None
    motivations_json: MotivationsProfile | None = None
    values_json: Any = None
    roles_json: Any = None
    skills_json: Any = None
    traits_json: Any = None
    metadata_json: Any = None
    sources_used: Any = None
    values: list[MiniDetailValue] = []
    roles: dict = {}
    skills: list[str] = []
    traits: list[str] = []
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @field_validator(
        "personality_typology_json", "behavioral_context_json", "motivations_json", mode="before"
    )
    @classmethod
    def parse_structured_json(cls, value: Any) -> Any:
        return _parse_json_value(value)

    @model_validator(mode="after")
    def parse_values(self) -> "MiniPublic":
        if self.values_json:
            try:
                data = MiniDetail._parse_json(self.values_json)
                if data:
                    eng_values = data.get("engineering_values", [])
                    self.values = [
                        MiniDetailValue(
                            name=v.get("name", ""),
                            description=v.get("description", ""),
                            intensity=v.get("intensity", 0.5),
                        )
                        for v in eng_values
                    ]
            except (KeyError, TypeError):
                pass
        if self.roles_json:
            parsed = MiniDetail._parse_json(self.roles_json)
            if parsed:
                self.roles = parsed
        if self.skills_json:
            parsed = MiniDetail._parse_json(self.skills_json)
            if parsed:
                self.skills = parsed
        if self.traits_json:
            parsed = MiniDetail._parse_json(self.traits_json)
            if parsed:
                self.traits = parsed
        return self


class MiniTrustedService(BaseModel):
    """Minimal private mini payload for trusted service integrations."""

    id: str
    username: str
    display_name: str | None
    avatar_url: str | None
    status: str
    system_prompt: str | None

    model_config = {"from_attributes": True}


class ReviewPrivateAssessment(BaseModel):
    blocking_issues: list[Any] = Field(default_factory=list)
    non_blocking_issues: list[Any] = Field(default_factory=list)
    open_questions: list[Any] = Field(default_factory=list)
    positive_signals: list[Any] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = {"extra": "allow"}


class ReviewDeliveryPolicy(BaseModel):
    author_model: str | None = None
    context: str | None = None
    strictness: str | None = None
    teaching_mode: bool | None = None
    shield_author_from_noise: bool | None = None

    model_config = {"extra": "allow"}


class ReviewExpressedFeedback(BaseModel):
    summary: str = ""
    comments: list[Any] = Field(default_factory=list)
    approval_state: Literal["approve", "comment", "request_changes", "uncertain"] | None = None

    model_config = {"extra": "allow"}


class StructuredReviewState(BaseModel):
    private_assessment: ReviewPrivateAssessment
    delivery_policy: ReviewDeliveryPolicy | None = None
    expressed_feedback: ReviewExpressedFeedback

    model_config = {"extra": "allow"}


class ReviewCyclePredictionUpsertRequest(BaseModel):
    external_id: str = Field(max_length=255)
    source_type: str = Field(default="github", max_length=50)
    predicted_state: StructuredReviewState
    metadata_json: dict[str, Any] | None = None


class ReviewCycleOutcomeUpdateRequest(BaseModel):
    external_id: str = Field(max_length=255)
    source_type: str = Field(default="github", max_length=50)
    human_review_outcome: StructuredReviewState
    delta_metrics: dict[str, Any] = Field(default_factory=dict)


class ReviewCycleRecord(BaseModel):
    id: str
    mini_id: str
    source_type: str
    external_id: str
    metadata_json: dict[str, Any] | None = None
    predicted_state: StructuredReviewState
    human_review_outcome: StructuredReviewState | None = None
    delta_metrics: dict[str, Any] | None = None
    predicted_at: datetime.datetime
    human_reviewed_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @field_validator("predicted_state", "human_review_outcome", "delta_metrics", mode="before")
    @classmethod
    def parse_review_cycle_json(cls, value: Any) -> Any:
        return _parse_json_value(value) if value is not None else value


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
