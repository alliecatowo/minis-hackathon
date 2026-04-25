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


ArtifactTypeV1 = Literal["pull_request", "design_doc", "issue_plan"]
ArtifactReviewTypeV1 = Literal["design_doc", "issue_plan"]


class ReviewRelationshipContextV1(BaseModel):
    """Explicit reviewer-author/team context for private-to-expressed review policy."""

    reviewer_author_relationship: Literal[
        "trusted_peer",
        "junior_mentorship",
        "senior_peer",
        "cross_team_partner",
        "unknown",
    ] = "unknown"
    trust_level: Literal["high", "medium", "low", "unknown"] = "unknown"
    mentorship_context: Literal[
        "reviewer_mentors_author",
        "peer",
        "none",
        "unknown",
    ] = "unknown"
    channel: Literal["public_review", "private_review", "team_private", "unknown"] = "unknown"
    team_alignment: Literal["same_team", "cross_team", "external", "unknown"] = "unknown"
    repo_ownership: Literal[
        "reviewer_owned",
        "author_owned",
        "shared",
        "unowned",
        "unknown",
    ] = "unknown"
    audience_sensitivity: Literal["low", "medium", "high", "unknown"] = "unknown"
    data_confidence: Literal["explicit", "derived", "unknown"] = "unknown"
    rationale: str = "Relationship/team context unknown; no relationship-specific assumptions applied."
    unknown_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_unknown_fields(self) -> "ReviewRelationshipContextV1":
        unknown_fields = [
            field_name
            for field_name in (
                "reviewer_author_relationship",
                "trust_level",
                "mentorship_context",
                "channel",
                "team_alignment",
                "repo_ownership",
                "audience_sensitivity",
            )
            if getattr(self, field_name) == "unknown"
        ]
        if unknown_fields:
            self.unknown_fields = unknown_fields
        return self


class ArtifactReviewRequestBaseV1(BaseModel):
    artifact_type: ArtifactTypeV1
    repo_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    diff_summary: str | None = Field(default=None, max_length=50000)
    artifact_summary: str | None = Field(default=None, max_length=50000)
    changed_files: list[str] = Field(default_factory=list, max_length=200)
    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"] = "unknown"
    delivery_context: Literal["hotfix", "normal", "exploratory", "incident"] = "normal"
    relationship_context: ReviewRelationshipContextV1 | None = None

    @model_validator(mode="after")
    def validate_has_review_input(self) -> "ArtifactReviewRequestBaseV1":
        if any(
            [
                self.title and self.title.strip(),
                self.description and self.description.strip(),
                self.diff_summary and self.diff_summary.strip(),
                self.artifact_summary and self.artifact_summary.strip(),
                self.changed_files,
            ]
        ):
            return self
        raise ValueError(
            "Provide at least one of title, description, diff_summary, artifact_summary, or changed_files"
        )


class ReviewPredictionRequestV1(ArtifactReviewRequestBaseV1):
    artifact_type: Literal["pull_request"] = "pull_request"


class PatchAdvisorRequestV1(ArtifactReviewRequestBaseV1):
    artifact_type: Literal["pull_request"] = "pull_request"


class ArtifactReviewRequestV1(ArtifactReviewRequestBaseV1):
    artifact_type: ArtifactReviewTypeV1


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


# -- Decision framework schemas (ALLIE-503) --


DecisionFrameworkPriority = Literal["low", "medium", "high", "critical"]
DecisionFrameworkSpecificityLevel = Literal[
    "global",
    "scope_local",
    "contextual",
    "case_pattern",
]


class DecisionFrameworkTemporalSpan(BaseModel):
    """Source-time coverage for a synthesized decision framework."""

    first_seen_at: str | None = None
    last_reinforced_at: str | None = None
    source_dates: list[str] = Field(default_factory=list)


class DecisionFrameworkEvidenceProvenance(BaseModel):
    """Auditable provenance attached to a framework's supporting evidence."""

    id: str | None = None
    source_type: str | None = None
    item_type: str | None = None
    evidence_date: str | None = None
    created_at: str | None = None
    source_uri: str | None = None
    visibility: str | None = None
    provenance_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = {"extra": "allow"}


class ConfidenceHistoryEntry(BaseModel):
    """Single audit record for a confidence adjustment on a DecisionFramework."""

    revision: int
    prior_confidence: float
    new_confidence: float
    delta: float
    outcome_type: str  # e.g. "confirmed", "missed", "overpredicted", "escalated"
    issue_key: str
    cycle_id: str
    applied_at: str  # ISO 8601 UTC


class DecisionFramework(BaseModel):
    """Reusable decision policy derived from principles, motivations, and evidence."""

    framework_id: str
    condition: str
    priority: DecisionFrameworkPriority
    tradeoff: str
    escalation_threshold: str
    counterexamples: list[str] = Field(default_factory=list)
    temporal_span: DecisionFrameworkTemporalSpan = Field(
        default_factory=DecisionFrameworkTemporalSpan
    )
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_provenance: list[DecisionFrameworkEvidenceProvenance] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    specificity_level: DecisionFrameworkSpecificityLevel
    value_ids: list[str] = Field(default_factory=list)
    motivation_ids: list[str] = Field(default_factory=list)
    decision_order: list[str] = Field(default_factory=list)
    approval_policy: str | None = None
    block_policy: str | None = None
    expression_policy: str | None = None
    exceptions: list[str] = Field(default_factory=list)
    source_type: str | None = None
    version: Literal["framework-model-v1"] = "framework-model-v1"
    # Outcome-driven learning fields (added for confidence delta loop)
    revision: int = 0
    confidence_history: list[ConfidenceHistoryEntry] = Field(default_factory=list)


class DecisionFrameworkProfile(BaseModel):
    """Versioned collection of synthesized decision frameworks."""

    version: Literal["decision_frameworks_v1"] = "decision_frameworks_v1"
    frameworks: list[DecisionFramework] = Field(default_factory=list)
    source: Literal["principles_motivations_normalizer"] = "principles_motivations_normalizer"


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
    ranking_signals: list["ReviewPredictionEvidenceRankingSignalV1"] = Field(
        default_factory=list
    )


class ReviewPredictionEvidenceRankingSignalV1(BaseModel):
    name: Literal[
        "lexical_relevance",
        "durable_framework",
        "recent_local_context",
        "framework_relevance",
        "relationship_context",
        "audience_context",
    ]
    value: float = Field(ge=0.0, le=1.0)
    reason: str


class ReviewPredictionFrameworkSignalV1(BaseModel):
    framework_id: str
    name: str
    summary: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    revision: int | None = None
    revision_count: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_provenance: list[DecisionFrameworkEvidenceProvenance] = Field(
        default_factory=list
    )
    provenance_ids: list[str] = Field(default_factory=list)
    temporal_stability_bonus: float = Field(default=0.0, ge=0.0)
    scope_match_boost: float = Field(default=0.0, ge=0.0)


class ReviewFrameworkTemporalBalanceV1(BaseModel):
    visible_stable_framework_ids: list[str] = Field(default_factory=list)
    visible_project_preference_ids: list[str] = Field(default_factory=list)
    stable_frameworks_preserved: bool = False
    rationale: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ReviewFrameworkConflictDecisionV1(BaseModel):
    framework_id: str
    disposition: Literal["win", "defer", "suppress"]


class ReviewFrameworkConflictResolutionV1(BaseModel):
    winning_framework_ids: list[str] = Field(default_factory=list)
    deferred_framework_ids: list[str] = Field(default_factory=list)
    suppressed_framework_ids: list[str] = Field(default_factory=list)
    tradeoff_rationale: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance_ids: list[str] = Field(default_factory=list)
    decisions: list[ReviewFrameworkConflictDecisionV1] = Field(default_factory=list)


class ReviewPredictionSignalV1(BaseModel):
    key: str
    summary: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    specificity: Literal[
        "framework_specific",
        "evidence_backed",
        "request_context_only",
        "insufficient",
    ] = "insufficient"
    evidence: list[ReviewPredictionEvidenceV1] = Field(default_factory=list)
    # Framework attribution: which decision framework drove this signal, and how
    # many times that framework has been revised through the learning loop.
    # Both are optional so the schema remains backward-compatible with existing
    # predictions produced before ALLIE-461.
    framework_id: str | None = None
    revision: int | None = None


class ReviewPredictionPrivateAssessmentV1(BaseModel):
    blocking_issues: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    non_blocking_issues: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    open_questions: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    positive_signals: list[ReviewPredictionSignalV1] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewPredictionDeliveryPolicyV1(BaseModel):
    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"]
    context: Literal["hotfix", "normal", "exploratory", "incident"]
    relationship_context: ReviewRelationshipContextV1 = Field(
        default_factory=ReviewRelationshipContextV1
    )
    strictness: Literal["low", "medium", "high"]
    teaching_mode: bool
    shield_author_from_noise: bool
    # Explicit policy routing for private→expressed transformation.
    # These control which assessment buckets are surfaced now, deferred, or suppressed.
    say: list[str] = Field(default_factory=lambda: ["blocking", "non_blocking", "questions", "positive"])
    suppress: list[str] = Field(default_factory=list)
    defer: list[str] = Field(default_factory=list)
    # Minimum confidence threshold for surfaced items in each bucket.
    # Lower means more items can cross from private assessment into expressed feedback.
    risk_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    rationale: str


class ReviewPredictionCommentV1(BaseModel):
    type: Literal["blocker", "note", "question", "praise"]
    disposition: Literal["request_changes", "comment", "approve"]
    issue_key: str | None = None
    specificity: Literal[
        "framework_specific",
        "evidence_backed",
        "request_context_only",
        "insufficient",
    ] = "insufficient"
    summary: str
    rationale: str


class ReviewPredictionExpressedFeedbackV1(BaseModel):
    summary: str
    comments: list[ReviewPredictionCommentV1] = Field(default_factory=list)
    approval_state: Literal["approve", "comment", "request_changes", "uncertain"]


class ReviewPredictionExpressionDeltaV1(BaseModel):
    """How a private assessment item moved into, or out of, expressed feedback."""

    issue_key: str
    private_bucket: Literal["blocking", "non_blocking", "questions", "positive"]
    expressed_disposition: Literal[
        "expressed",
        "deferred",
        "suppressed",
        "below_threshold",
    ]
    specificity: Literal[
        "framework_specific",
        "evidence_backed",
        "request_context_only",
        "insufficient",
    ] = "insufficient"
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class ArtifactSummaryV1(BaseModel):
    artifact_type: ArtifactTypeV1 = "pull_request"
    title: str | None = None


class ArtifactReviewV1(BaseModel):
    version: Literal["artifact_review_v1"] = "artifact_review_v1"
    prediction_available: bool = True
    mode: Literal["llm", "local_smoke", "gated"] = "llm"
    unavailable_reason: str | None = None
    reviewer_username: str
    repo_name: str | None = None
    artifact_summary: ArtifactSummaryV1 | None = None
    relationship_context: ReviewRelationshipContextV1 = Field(
        default_factory=ReviewRelationshipContextV1
    )
    private_assessment: ReviewPredictionPrivateAssessmentV1
    delivery_policy: ReviewPredictionDeliveryPolicyV1
    expressed_feedback: ReviewPredictionExpressedFeedbackV1
    private_expressed_deltas: list[ReviewPredictionExpressionDeltaV1] = Field(
        default_factory=list
    )
    framework_conflict_resolution: ReviewFrameworkConflictResolutionV1 | None = None
    framework_temporal_balance: ReviewFrameworkTemporalBalanceV1 | None = None


class ReviewPredictionV1(ArtifactReviewV1):
    version: Literal["review_prediction_v1"] = "review_prediction_v1"
    framework_signals: list[ReviewPredictionFrameworkSignalV1] = Field(default_factory=list)
    framework_conflict_resolution: ReviewFrameworkConflictResolutionV1 | None = None


class PatchAdvisorGuidanceV1(BaseModel):
    key: str
    summary: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    framework_id: str | None = None
    revision: int | None = None
    evidence: list[ReviewPredictionEvidenceV1] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance_ids: list[str] = Field(default_factory=list)


class PatchAdvisorEvidenceReferenceV1(BaseModel):
    framework_id: str
    summary: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    revision: int | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    provenance_ids: list[str] = Field(default_factory=list)
    evidence_provenance: list[DecisionFrameworkEvidenceProvenance] = Field(
        default_factory=list
    )


class PatchAdvisorV1(BaseModel):
    version: Literal["patch_advisor_v1"] = "patch_advisor_v1"
    advice_available: bool = True
    mode: Literal["framework", "gated"] = "framework"
    unavailable_reason: str | None = None
    reviewer_username: str
    repo_name: str | None = None
    artifact_summary: ArtifactSummaryV1 | None = None
    framework_signals: list[ReviewPredictionFrameworkSignalV1] = Field(default_factory=list)
    change_plan: list[PatchAdvisorGuidanceV1] = Field(default_factory=list)
    do_not_change: list[PatchAdvisorGuidanceV1] = Field(default_factory=list)
    risks: list[PatchAdvisorGuidanceV1] = Field(default_factory=list)
    expected_reviewer_objections: list[PatchAdvisorGuidanceV1] = Field(default_factory=list)
    evidence_references: list[PatchAdvisorEvidenceReferenceV1] = Field(default_factory=list)
    review_prediction: ReviewPredictionV1 | None = None


ReviewArtifactSummaryV1 = ArtifactSummaryV1


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


ArtifactReviewOutcomeValueV1 = Literal["accepted", "rejected", "revised", "deferred"]


class ArtifactReviewSuggestionOutcomeV1(BaseModel):
    suggestion_key: str = Field(min_length=1, max_length=255)
    outcome: ArtifactReviewOutcomeValueV1
    summary: str | None = Field(default=None, max_length=2000)


class ArtifactReviewOutcomeCaptureV1(BaseModel):
    artifact_outcome: ArtifactReviewOutcomeValueV1 | None = None
    final_disposition: str | None = Field(default=None, max_length=100)
    reviewer_summary: str | None = Field(default=None, max_length=5000)
    suggestion_outcomes: list[ArtifactReviewSuggestionOutcomeV1] = Field(default_factory=list)


class StructuredReviewState(BaseModel):
    private_assessment: ReviewPrivateAssessment
    delivery_policy: ReviewDeliveryPolicy | None = None
    expressed_feedback: ReviewExpressedFeedback
    outcome_capture: ArtifactReviewOutcomeCaptureV1 | None = None

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


class ArtifactReviewCyclePredictionUpsertRequest(BaseModel):
    external_id: str = Field(max_length=255)
    artifact_type: ArtifactReviewTypeV1
    predicted_state: ArtifactReviewV1
    metadata_json: dict[str, Any] | None = None


class ArtifactReviewCycleOutcomeUpdateRequest(BaseModel):
    external_id: str = Field(max_length=255)
    artifact_type: ArtifactReviewTypeV1
    human_outcome: ArtifactReviewOutcomeCaptureV1


class ArtifactReviewCycleRecord(BaseModel):
    id: str
    mini_id: str
    artifact_type: str
    external_id: str
    metadata_json: dict[str, Any] | None = None
    predicted_state: ArtifactReviewV1
    human_outcome: ArtifactReviewOutcomeCaptureV1 | None = None
    delta_metrics: dict[str, Any] | None = None
    predicted_at: datetime.datetime
    finalized_at: datetime.datetime | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}

    @field_validator("predicted_state", "human_outcome", "delta_metrics", mode="before")
    @classmethod
    def parse_artifact_cycle_json(cls, value: Any) -> Any:
        return _parse_json_value(value) if value is not None else value


class AgreementScorecardTrend(BaseModel):
    direction: Literal["up", "down", "flat", "insufficient_data"]
    delta: float | None = Field(default=None, ge=-1.0, le=1.0)


class AgreementScorecardSummary(BaseModel):
    mini_id: str
    username: str
    cycles_count: int = Field(ge=0)
    approval_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    blocker_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    comment_overlap: float | None = Field(default=None, ge=0.0, le=1.0)
    trend: AgreementScorecardTrend


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


# -- Frameworks-at-risk schemas (ALLIE-519) --

AtRiskReason = Literal["low_band", "declining_trend", "low_evidence"]


class AtRiskFramework(BaseModel):
    """A framework flagged for owner review via the active-learning loop."""

    framework_id: str
    condition: str
    action: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    revision: int = 0
    confidence_history: list[ConfidenceHistoryEntry] = Field(default_factory=list)
    reason: AtRiskReason
    # Human-readable decline trend summary, e.g. "↘ -0.15 over 4 cycles"
    trend_summary: str | None = None
    retired: bool = False


class RetireFrameworkResponse(BaseModel):
    """Response after retiring a framework."""

    framework_id: str
    retired: bool
    message: str
