from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ReviewCycle
from app.models.schemas import (
    ArtifactReviewRequestBaseV1,
    ArtifactReviewV1,
    ArtifactSummaryV1,
    BehavioralContext,
    MotivationsProfile,
    PatchAdvisorEvidenceReferenceV1,
    PatchAdvisorGuidanceV1,
    PatchAdvisorRequestV1,
    PatchAdvisorV1,
    ReviewPredictionFrameworkSignalV1,
    ReviewPredictionExpressionDeltaV1,
    ReviewFrameworkConflictDecisionV1,
    ReviewFrameworkConflictResolutionV1,
    ReviewPredictionCommentV1,
    ReviewFrameworkTemporalBalanceV1,
    ReviewPredictionDeliveryPolicyV1,
    ReviewPredictionEvidenceRankingSignalV1,
    ReviewPredictionEvidenceV1,
    ReviewPredictionExpressedFeedbackV1,
    ReviewPredictionPrivateAssessmentV1,
    ReviewPredictionRequestV1,
    ReviewPredictionSignalV1,
    ReviewPredictionV1,
    ReviewRelationshipContextV1,
    _parse_json_value,
)

_REVIEW_CONTEXT_KEYS = {"code_review", "review", "pr_review", "technical_discussion"}
_RISK_KEYWORDS = {
    "security",
    "auth",
    "authorization",
    "permission",
    "secret",
    "token",
    "oauth",
    "jwt",
    "credential",
    "database",
    "migration",
    "schema",
    "backfill",
    "sql",
    "cache",
    "queue",
    "worker",
    "async",
    "concurrency",
    "retry",
    "timeout",
    "billing",
    "payment",
    "webhook",
    "contract",
    "rollback",
}
_TEST_KEYWORDS = {"test", "tests", "testing", "coverage", "spec", "pytest", "unittest"}
_ROLLOUT_KEYWORDS = {"flag", "feature flag", "metrics", "monitor", "rollback", "logging", "alert"}
_DOC_KEYWORDS = {"docs", "documentation", "readme", "comment", "comments"}
_DIRECT_REVIEW_KEYWORDS = {"direct", "blunt", "sharp", "terse", "firm", "specific"}
_HIGH_BAR_KEYWORDS = {
    "missing tests",
    "coverage",
    "precision",
    "quality",
    "explicit",
    "boundary",
    "boundaries",
    "rollback",
    "migration plan",
    "breakage",
    "regression",
}
_NOISE_SHIELD_KEYWORDS = {
    "noise",
    "noisy",
    "nit",
    "nits",
    "bike-shed",
    "bikeshed",
    "verbosity",
    "churn",
    "back-and-forth",
    "pedantic",
}
_TEACHING_KEYWORDS = {
    "mentor",
    "mentoring",
    "teach",
    "teaching",
    "coach",
    "coaching",
    "guide",
    "guidance",
    "onboard",
    "onboarding",
    "explain",
    "explains",
}
_INCIDENT_CONTEXT_KEYWORDS = {
    "incident",
    "outage",
    "sev",
    "mitigation",
    "mitigate",
    "restore",
    "recovery",
    "degraded",
}
_HOTFIX_CONTEXT_KEYWORDS = {
    "hotfix",
    "urgent fix",
    "quick fix",
    "patch release",
    "patch",
}
_EXPLORATORY_CONTEXT_KEYWORDS = {
    "exploratory",
    "prototype",
    "spike",
    "wip",
    "draft",
    "experiment",
    "poc",
    "proof of concept",
}

_SOURCE_CONFIDENCE = {
    "principles": 0.95,
    "behavioral_context": 0.9,
    "motivations": 0.82,
    "memory": 0.72,
    "evidence": 0.66,
    "input": 0.4,
}
_RECENCY_HINT_KEYWORDS = {
    "recent",
    "recently",
    "latest",
    "today",
    "yesterday",
    "this week",
    "last week",
}
_PRECEDENT_THEME_KEYWORDS = {
    "tests": _TEST_KEYWORDS,
    "rollout": _ROLLOUT_KEYWORDS | {"rollback", "compatibility", "backward compatibility"},
    "auth": {"auth", "authorization", "permission", "token", "oauth", "jwt", "security"},
    "migration": {"migration", "schema", "database", "sql", "contract", "backfill"},
    "runtime": {"cache", "async", "queue", "worker", "concurrency", "retry", "timeout"},
    "docs": _DOC_KEYWORDS,
}
_DELIVERY_BUCKETS = ("blocking", "non_blocking", "questions", "positive")
_STRICTNESS_RISK_THRESHOLD: dict[str, float] = {
    "low": 0.74,
    "medium": 0.65,
    "high": 0.60,
}
_REPO_CONTEXT_CRITICAL_TOKENS = {
    "security",
    "auth",
    "payments",
    "billing",
    "finance",
    "secrets",
    "crypto",
}
_REPO_CONTEXT_PLATFORM_TOKENS = {
    "platform",
    "infra",
    "infrastructure",
    "core",
}
_FRAMEWORK_SIGNAL_COUNT = 5
_TEMPORAL_STABILITY_WINDOW_SHORT_DAYS = 365
_TEMPORAL_STABILITY_WINDOW_LONG_DAYS = 730
_TEMPORAL_DURABILITY_SHORT_BONUS = 0.10
_TEMPORAL_DURABILITY_LONG_BONUS = 0.20
_SCOPE_LOCAL_BOOST = 0.15
_FRAMEWORK_SIGNAL_STOPWORDS = {
    "the",
    "and",
    "or",
    "for",
    "to",
    "with",
    "that",
    "this",
    "these",
    "those",
    "they",
    "will",
    "from",
    "into",
    "when",
    "where",
    "what",
    "how",
    "why",
    "should",
    "would",
}
_FRAMEWORK_ARCHITECTURE_TERMS = {
    "architecture",
    "architectural",
    "abstraction",
    "boundary",
    "boundaries",
    "contract",
    "correctness",
    "durable",
    "long-term",
    "migration",
    "schema",
    "interface",
    "api",
    "seam",
}
_FRAMEWORK_SHIPPING_TERMS = {
    "ship",
    "shipping",
    "speed",
    "velocity",
    "hotfix",
    "incident",
    "patch",
    "restore",
    "mitigate",
    "mitigation",
    "quick",
    "quickly",
    "pragmatic",
    "pragmatism",
}
_FRAMEWORK_MENTORSHIP_TERMS = {
    "mentor",
    "mentorship",
    "teach",
    "teaching",
    "coach",
    "coaching",
    "guide",
    "guidance",
    "junior",
}
_FRAMEWORK_LOCAL_NORM_TERMS = {
    "repo",
    "local",
    "precedent",
    "pattern",
    "existing",
    "convention",
    "norm",
}
_RELATIONSHIP_TERMS = {
    "junior_peer": {
        "junior",
        "newer",
        "newcomer",
        "onboard",
        "onboarding",
        "mentee",
    },
    "trusted_peer": {
        "trusted",
        "collaborator",
        "peer",
        "teammate",
        "high-trust",
        "high trust",
        "known",
    },
    "senior_peer": {
        "senior",
        "staff",
        "principal",
        "experienced",
        "peer",
        "maintainer",
    },
    "unknown": {
        "unknown",
        "external",
        "contributor",
        "oss",
        "open source",
    },
}
_AUDIENCE_TERMS = {
    "junior_peer": {
        "junior",
        "public",
        "cross-team",
        "cross team",
        "teaching",
        "coaching",
        "onboarding",
    },
    "trusted_peer": {
        "trusted",
        "teammate",
        "peer",
        "private",
        "same-team",
        "same team",
    },
    "senior_peer": {
        "senior",
        "staff",
        "peer",
        "maintainer",
    },
    "unknown": {
        "unknown",
        "public",
        "cross-team",
        "cross team",
        "external",
        "oss",
        "open source",
    },
}


def _term_variants(value: str) -> set[str]:
    normalized = value.strip().lower()
    if not normalized or normalized == "unknown":
        return set()
    return {normalized, normalized.replace("_", "-"), normalized.replace("_", " ")}


def _relationship_terms_for_context(
    author_model: str,
    relationship_context: ReviewRelationshipContextV1 | None,
) -> set[str]:
    terms: set[str] = set()
    if author_model != "unknown":
        terms.update(_RELATIONSHIP_TERMS.get(author_model, set()))

    if relationship_context and relationship_context.data_confidence != "unknown":
        for field_name in (
            "reviewer_author_relationship",
            "trust_level",
            "mentorship_context",
        ):
            terms.update(_term_variants(str(getattr(relationship_context, field_name))))
    return terms


def _audience_terms_for_context(
    author_model: str,
    relationship_context: ReviewRelationshipContextV1 | None,
) -> set[str]:
    terms = set(_AUDIENCE_TERMS.get(author_model, set()))
    if relationship_context and relationship_context.data_confidence != "unknown":
        for field_name in ("channel", "team_alignment", "audience_sensitivity"):
            terms.update(_term_variants(str(getattr(relationship_context, field_name))))
        if relationship_context.channel == "public_review":
            terms.add("public")
        if relationship_context.team_alignment == "cross_team":
            terms.update({"cross-team", "cross team"})
        if relationship_context.team_alignment == "external":
            terms.update({"external", "oss", "open source"})
    return terms


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _tokenize(value: str) -> list[str]:
    return re.findall(r"[a-z0-9_./-]+", value.lower())


def _parse_behavioral_context(raw: Any) -> BehavioralContext | None:
    parsed = _parse_json_value(raw)
    if not parsed:
        return None
    try:
        return BehavioralContext.model_validate(parsed)
    except Exception:
        return None


def _parse_motivations(raw: Any) -> MotivationsProfile | None:
    parsed = _parse_json_value(raw)
    if not parsed:
        return None
    try:
        return MotivationsProfile.model_validate(parsed)
    except Exception:
        return None


def _parse_values(raw: Any) -> dict[str, Any]:
    parsed = _parse_json_value(raw)
    return parsed if isinstance(parsed, dict) else {}


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value:
        return None
    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            value = item.strip()
            if value:
                out.append(value)
    return out


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _coerce_confidence(raw: Any, default: float = 0.5) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _coerce_int(raw: Any, default: int = 0) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _tokenise_text(value: str | None) -> set[str]:
    tokens = {token for token in _tokenize(value or "") if len(token) > 2 and token not in _FRAMEWORK_SIGNAL_STOPWORDS}
    if not tokens:
        return set()
    return tokens


def _extract_decision_frameworks(principles_json: Any) -> list[dict[str, Any]]:
    if not isinstance(principles_json, dict):
        return []
    df_payload = principles_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        return []
    raw_frameworks = df_payload.get("frameworks")
    if not isinstance(raw_frameworks, list):
        return []

    frameworks: list[dict[str, Any]] = []
    for raw in raw_frameworks:
        if not isinstance(raw, dict):
            continue
        if raw.get("retired"):
            continue
        framework_id = str(raw.get("framework_id", "")).strip()
        if not framework_id:
            continue
        frameworks.append(raw)
    return frameworks


def _framework_signal_text(fw: dict[str, Any]) -> str:
    decision_order = _string_list(fw.get("decision_order"))
    value_ids = _string_list(fw.get("value_ids"))
    value_text = ""
    if value_ids:
        value_text = " / ".join(value_ids)
    parts = [
        str(fw.get("condition") or ""),
        str(fw.get("trigger") or ""),
        str(fw.get("action") or ""),
        str(fw.get("tradeoff") or ""),
        str(fw.get("escalation_threshold") or ""),
        value_text,
    ]
    if decision_order:
        parts.append(" ".join(decision_order))
    return " ".join(part for part in parts if part).strip()


def _cohere_framework_signal_reason(
    framework_text: str,
    matched_terms: set[str],
) -> str:
    if matched_terms:
        terms = ", ".join(sorted(matched_terms))
        return f"Matched request terms [{terms}] to this framework condition/action."
    return "This high-confidence framework is one of the top learned rules in this mini."


def _resolve_framework_conflicts(
    signals: list[ReviewPredictionFrameworkSignalV1],
    *,
    body: ArtifactReviewRequestBaseV1,
    policy: ReviewPredictionDeliveryPolicyV1,
) -> ReviewFrameworkConflictResolutionV1 | None:
    if len(signals) < 2:
        return None

    request_tokens = _tokenise_text(_build_request_text(body))
    architectural_change = bool(request_tokens & _FRAMEWORK_ARCHITECTURE_TERMS) or _has_matching_file(
        body.changed_files,
        ("api", "schema", "migration", "architecture", "interface", "contract"),
    )
    scored: list[tuple[float, ReviewPredictionFrameworkSignalV1, set[str], list[str]]] = []
    for signal in signals:
        frame_tokens = _tokenise_text(
            f"{signal.framework_id} {signal.name} {signal.summary} {signal.reason}"
        )
        dimensions: set[str] = set()
        if frame_tokens & _FRAMEWORK_ARCHITECTURE_TERMS:
            dimensions.add("architecture")
        if frame_tokens & _FRAMEWORK_SHIPPING_TERMS:
            dimensions.add("shipping_speed")
        if frame_tokens & _FRAMEWORK_MENTORSHIP_TERMS:
            dimensions.add("mentorship")
        if frame_tokens & _FRAMEWORK_LOCAL_NORM_TERMS:
            dimensions.add("local_repo_norm")
        if not dimensions:
            dimensions.add("general")

        score = signal.confidence
        context_boost = 0.0
        reasons: list[str] = []
        if policy.context in {"hotfix", "incident"}:
            if "shipping_speed" in dimensions:
                context_boost += 0.2
                reasons.append(f"{policy.context} pressure favors restoring service over broadening scope")
            if "architecture" in dimensions:
                context_boost -= 0.12
                reasons.append("architecture concerns are preserved but deferred under delivery pressure")
            if "mentorship" in dimensions:
                context_boost -= 0.08
                reasons.append("coaching detail is narrowed while the fix is time-sensitive")
            if "local_repo_norm" in dimensions:
                context_boost += 0.05
                reasons.append("local precedent helps keep a hotfix low-risk")
        elif architectural_change:
            if "architecture" in dimensions:
                context_boost += 0.18
                reasons.append("architectural-change context favors durable boundaries and correctness")
            if "shipping_speed" in dimensions:
                context_boost -= 0.06
                reasons.append("shipping-speed pressure is secondary when the change sets structure")
        elif policy.context == "exploratory":
            if "mentorship" in dimensions:
                context_boost += 0.12
                reasons.append("exploratory work benefits from guidance over blocking")
            if "shipping_speed" in dimensions:
                context_boost += 0.04
                reasons.append("prototype context rewards low-friction iteration")

        if _is_junior_mentorship(policy.relationship_context, body.author_model) and "mentorship" in dimensions:
            context_boost += 0.1
            reasons.append("junior/mentorship context favors mentorship")

        scored.append((_coerce_confidence(score + context_boost), signal, dimensions, reasons))

    dimensions_seen = {
        dimension for _score, _signal, dimensions, _reasons in scored for dimension in dimensions
    }
    if len(dimensions_seen - {"general"}) < 2:
        return None

    scored.sort(key=lambda item: (item[0], item[1].confidence), reverse=True)
    top_score = scored[0][0]
    winners = [item for item in scored if top_score - item[0] <= 0.03]
    winning_ids = [signal.framework_id for _score, signal, _dimensions, _reasons in winners]

    evidence_ids = []
    provenance_ids = []
    decisions: list[ReviewFrameworkConflictDecisionV1] = []
    deferred_ids: list[str] = []
    suppressed_ids: list[str] = []
    rationale_parts: list[str] = []
    for _score, signal, dimensions, reasons in scored:
        evidence_ids.extend(signal.evidence_ids)
        provenance_ids.extend(signal.provenance_ids)
        if signal.framework_id in winning_ids:
            disposition = "win"
            rationale_parts.extend(reasons or ["highest fit after context-sensitive framework scoring"])
        elif policy.context in {"hotfix", "incident"} and "architecture" in dimensions:
            disposition = "defer"
            deferred_ids.append(signal.framework_id)
        elif architectural_change and "shipping_speed" in dimensions:
            disposition = "defer"
            deferred_ids.append(signal.framework_id)
        else:
            disposition = "suppress"
            suppressed_ids.append(signal.framework_id)

        decisions.append(
            ReviewFrameworkConflictDecisionV1(
                framework_id=signal.framework_id,
                disposition=disposition,
            )
        )

    runner_up = scored[len(winners)][0] if len(scored) > len(winners) else top_score
    confidence = _coerce_confidence(0.58 + max(0.0, top_score - runner_up))

    return ReviewFrameworkConflictResolutionV1(
        winning_framework_ids=winning_ids,
        deferred_framework_ids=deferred_ids,
        suppressed_framework_ids=suppressed_ids,
        tradeoff_rationale=", ".join(_dedupe(rationale_parts)),
        confidence=confidence,
        evidence_ids=_dedupe(evidence_ids),
        provenance_ids=_dedupe(provenance_ids),
        decisions=decisions,
    )


def _temporal_stability_bonus(temporal_span: dict[str, Any]) -> float:
    first_seen = _parse_iso_datetime(temporal_span.get("first_seen_at"))
    last_reinforced = _parse_iso_datetime(temporal_span.get("last_reinforced_at"))
    if not first_seen or not last_reinforced:
        return 0.0
    span_days = max(0, (last_reinforced - first_seen).days)
    if span_days >= _TEMPORAL_STABILITY_WINDOW_LONG_DAYS:
        return _TEMPORAL_DURABILITY_LONG_BONUS
    if span_days >= _TEMPORAL_STABILITY_WINDOW_SHORT_DAYS:
        return _TEMPORAL_DURABILITY_SHORT_BONUS
    return 0.0


def _request_scope_tokens(body: ArtifactReviewRequestBaseV1) -> set[str]:
    tokens: set[str] = set()
    for path in body.changed_files:
        normalized = (path or "").replace("\\", "/").lower()
        if not normalized:
            continue
        for token in _tokenize(normalized):
            if len(token) > 2:
                tokens.add(token)
        path_segments = [segment for segment in normalized.split("/") if segment]
        for segment in path_segments:
            if segment and len(segment) > 2:
                tokens.add(segment)

    repo = _normalize_repo_name(body.repo_name)
    if repo:
        tokens.add(repo)
        for segment in repo.split("/"):
            if segment:
                tokens.add(segment)
    return tokens


def _framework_scope_match(raw: dict[str, Any], request_scope_tokens: set[str]) -> bool:
    if str(raw.get("specificity_level", "")).strip() != "scope_local":
        return False
    text = " ".join(
        str(raw.get(key, ""))
        for key in ("condition", "action", "decision_order", "value_ids", "name")
    )
    framework_scope_tokens = _tokenise_text(text)
    return bool(request_scope_tokens & framework_scope_tokens)


def _build_framework_scope_metadata(
    visible_signals: list[ReviewPredictionFrameworkSignalV1],
) -> ReviewFrameworkTemporalBalanceV1:
    visible_stable_framework_ids = [
        signal.framework_id
        for signal in visible_signals
        if signal.temporal_stability_bonus > 0.0
    ]
    visible_project_preference_ids = [
        signal.framework_id
        for signal in visible_signals
        if signal.scope_match_boost > 0.0
    ]
    stable_frameworks_preserved = bool(visible_stable_framework_ids)
    if stable_frameworks_preserved and visible_project_preference_ids:
        rationale = (
            "Scoped signals lead but durable temporal frameworks are preserved in visibility."
        )
    elif stable_frameworks_preserved:
        rationale = "Durable temporal frameworks remain visible with no competing scoped preferences."
    else:
        rationale = "No durable temporal frameworks were active for visibility balancing."

    return ReviewFrameworkTemporalBalanceV1(
        visible_stable_framework_ids=visible_stable_framework_ids,
        visible_project_preference_ids=visible_project_preference_ids,
        stable_frameworks_preserved=stable_frameworks_preserved,
        rationale=rationale,
        confidence=0.95 if stable_frameworks_preserved else 0.6,
    )


def _build_framework_signals(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
) -> tuple[list[ReviewPredictionFrameworkSignalV1], ReviewFrameworkTemporalBalanceV1 | None]:
    request_text = _build_request_text(body)
    request_tokens = _tokenise_text(request_text)
    if not request_tokens:
        request_tokens = set()
    request_scope_tokens = _request_scope_tokens(body)

    frameworks = _extract_decision_frameworks(getattr(mini, "principles_json", None))
    if not frameworks:
        return [], None

    scored: list[
        tuple[int, float, int, bool, bool, ReviewPredictionFrameworkSignalV1]
    ] = []
    for raw in frameworks:
        framework_id = str(raw.get("framework_id", "")).strip()
        if not framework_id:
            continue
        text_for_matching = _framework_signal_text(raw)
        fw_tokens = _tokenise_text(text_for_matching)
        matched_terms = request_tokens & fw_tokens
        matched_count = len(matched_terms)

        base_confidence = _coerce_confidence(raw.get("confidence"), default=0.5)
        temporal_span = raw.get("temporal_span")
        temporal_boost = (
            _temporal_stability_bonus(temporal_span) if isinstance(temporal_span, dict) else 0.0
        )
        scope_match_boost = (
            _SCOPE_LOCAL_BOOST
            if _framework_scope_match(raw, request_scope_tokens)
            else 0.0
        )
        confidence = _coerce_confidence(
            base_confidence + temporal_boost + scope_match_boost
        )
        is_stable_framework = temporal_boost > 0.0
        raw_revision = raw.get("revision")
        revision_count = _coerce_int(raw_revision, default=0)
        revision = revision_count if raw_revision is not None else None

        name = (
            str(raw.get("name") or "").strip()
            or str(raw.get("condition") or "").strip()
            or str(raw.get("trigger") or "").strip()
            or framework_id
        )
        summary = (
            f"When {raw.get('condition')}"
            if str(raw.get("condition", "")).strip()
            else str(raw.get("action") or "").strip() or "Decision framework rule"
        )
        if raw.get("action"):
            summary = f"{summary}; {str(raw.get('action')).strip()}"

        reason = _cohere_framework_signal_reason(text_for_matching, matched_terms)
        evidence_ids = _string_list(raw.get("evidence_ids"))
        provenance_payload = raw.get("evidence_provenance")
        if isinstance(provenance_payload, list):
            evidence_provenance = [item for item in provenance_payload if isinstance(item, dict)]
        else:
            evidence_provenance = []
        provenance_ids = [
            str(item.get("id"))
            for item in evidence_provenance
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
        ]

        framework_signal = ReviewPredictionFrameworkSignalV1(
            framework_id=framework_id,
            name=name,
            summary=summary[:240],
            reason=reason,
            confidence=confidence,
            revision=revision,
            revision_count=revision_count,
            evidence_ids=evidence_ids,
            evidence_provenance=evidence_provenance,
            provenance_ids=provenance_ids,
            temporal_stability_bonus=temporal_boost,
            scope_match_boost=scope_match_boost,
        )

        scored.append(
            (
                matched_count,
                confidence,
                revision_count,
                is_stable_framework,
                bool(scope_match_boost),
                framework_signal,
            )
        )

    matched = [entry for entry in scored if entry[0] > 0]
    ordered = sorted(
        matched if matched else scored,
        key=lambda item: (item[0], item[5].scope_match_boost, item[1], item[2], not item[3]),
        reverse=True,
    )
    if not ordered:
        return [], None

    visible = ordered[:_FRAMEWORK_SIGNAL_COUNT]
    if visible:
        has_stable = any(entry[3] for entry in visible)
        stable_candidates = [entry for entry in ordered if entry[3]]
        if stable_candidates and not has_stable:
            visible[-1] = stable_candidates[0]
            visible = sorted(
                visible,
                key=lambda item: (item[0], item[5].scope_match_boost, item[1], item[2]),
                reverse=True,
            )[:_FRAMEWORK_SIGNAL_COUNT]

    framework_signals = [entry[5] for entry in visible]
    if not framework_signals:
        return [], None
    return framework_signals, _build_framework_scope_metadata(framework_signals)


def _engineering_value(values: dict[str, Any], name: str) -> float:
    engineering_values = values.get("engineering_values", [])
    if not isinstance(engineering_values, list):
        return 0.0

    target = name.lower()
    for item in engineering_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("name", "")).lower() == target:
            try:
                return float(item.get("intensity", 0.0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _keyword_search_snippets(content: str, query: str, max_results: int = 3) -> list[str]:
    lines = [line.strip() for line in content.splitlines()]
    keywords = [word.lower() for word in query.split() if len(word) > 2]
    if not keywords:
        keywords = _tokenize(query)
    if not keywords:
        return []

    scored: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not line:
            continue
        lower_line = line.lower()
        score = sum(1 for keyword in keywords if keyword in lower_line)
        if score > 0:
            scored.append((score, index))

    scored.sort(key=lambda item: item[0], reverse=True)
    seen_indexes: set[int] = set()
    snippets: list[str] = []
    for _score, index in scored:
        if index in seen_indexes:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        for seen_index in range(start, end):
            seen_indexes.add(seen_index)
        snippet = " ".join(part for part in lines[start:end] if part)
        if snippet:
            snippets.append(snippet[:300])
        if len(snippets) >= max_results:
            break
    return snippets


def _build_request_text(body: ArtifactReviewRequestBaseV1) -> str:
    sections = [
        _normalize_text(body.artifact_type.replace("_", " ")),
        _normalize_text(body.repo_name),
        _normalize_text(body.title),
        _normalize_text(body.description),
        _normalize_text(body.artifact_summary),
        _normalize_text(body.diff_summary),
        "\n".join(body.changed_files),
    ]
    return "\n".join(section for section in sections if section)


def _artifact_kind_label(body: ArtifactReviewRequestBaseV1) -> str:
    return body.artifact_type.replace("_", " ")


def _artifact_scope_label(body: ArtifactReviewRequestBaseV1) -> str:
    if body.artifact_type == "pull_request":
        return "change"
    return "artifact"


def _normalize_repo_name(repo_name: str | None) -> str:
    return _normalize_text(repo_name).lower()


def _iter_review_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _review_state_text(review_state: dict[str, Any] | None) -> str:
    if not isinstance(review_state, dict):
        return ""

    parts: list[str] = []
    private_assessment = review_state.get("private_assessment")
    if isinstance(private_assessment, dict):
        for field in ("blocking_issues", "non_blocking_issues", "open_questions", "positive_signals"):
            for item in _iter_review_items(private_assessment.get(field)):
                for key in ("key", "id", "summary", "rationale", "body"):
                    value = _normalize_text(str(item.get(key, "")))
                    if value:
                        parts.append(value)

    expressed_feedback = review_state.get("expressed_feedback")
    if isinstance(expressed_feedback, dict):
        summary = _normalize_text(str(expressed_feedback.get("summary", "")))
        if summary:
            parts.append(summary)
        for item in _iter_review_items(expressed_feedback.get("comments")):
            for key in ("summary", "rationale", "body"):
                value = _normalize_text(str(item.get(key, "")))
                if value:
                    parts.append(value)

    return " ".join(parts).lower()


def _extract_approval_state(review_state: dict[str, Any] | None) -> str | None:
    if not isinstance(review_state, dict):
        return None
    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None
    approval_state = _normalize_text(str(expressed_feedback.get("approval_state", "")))
    return approval_state or None


def _summarize_same_repo_precedent(repo_name: str, cycles: list[ReviewCycle]) -> dict[str, Any] | None:
    if not cycles:
        return None

    focus_counts: dict[str, int] = {}
    approval_counts = {
        "approve": 0,
        "comment": 0,
        "request_changes": 0,
        "uncertain": 0,
    }

    for cycle in cycles:
        human_state = cycle.human_review_outcome if isinstance(cycle.human_review_outcome, dict) else None
        predicted_state = cycle.predicted_state if isinstance(cycle.predicted_state, dict) else None
        signal_text = _review_state_text(human_state) or _review_state_text(predicted_state)
        for theme, keywords in _PRECEDENT_THEME_KEYWORDS.items():
            if signal_text and _contains_any(signal_text, keywords):
                focus_counts[theme] = focus_counts.get(theme, 0) + 1

        approval_state = _extract_approval_state(human_state) or _extract_approval_state(predicted_state)
        if approval_state in approval_counts:
            approval_counts[approval_state] += 1

    focuses = [
        theme
        for theme, _count in sorted(
            focus_counts.items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )
    ][:3]
    dominant_approval = max(approval_counts.items(), key=lambda item: item[1])[0]

    detail_parts = [f"same-repo precedent for {repo_name}: {len(cycles)} recent review cycles"]
    if focuses:
        detail_parts.append(f"recurring focus on {', '.join(focuses)}")
    if approval_counts[dominant_approval] > 0:
        detail_parts.append(f"outcomes skewed {dominant_approval}")

    return {
        "repo_name": repo_name,
        "cycle_count": len(cycles),
        "focus_counts": focus_counts,
        "focuses": focuses,
        "approval_counts": approval_counts,
        "detail": "; ".join(detail_parts),
    }


async def load_same_repo_precedent(
    session: AsyncSession,
    mini_id: str | None,
    repo_name: str | None,
    limit: int = 6,
) -> dict[str, Any] | None:
    normalized_repo = _normalize_repo_name(repo_name)
    if not mini_id or not normalized_repo:
        return None

    result = await session.execute(
        select(ReviewCycle)
        .where(ReviewCycle.mini_id == mini_id)
        .order_by(ReviewCycle.updated_at.desc(), ReviewCycle.predicted_at.desc())
        .limit(limit * 4)
    )
    cycles = list(result.scalars())

    matched_cycles: list[ReviewCycle] = []
    for cycle in cycles:
        metadata = cycle.metadata_json if isinstance(cycle.metadata_json, dict) else {}
        cycle_repo = _normalize_repo_name(metadata.get("repo_full_name"))
        if cycle_repo != normalized_repo:
            continue
        matched_cycles.append(cycle)
        if len(matched_cycles) >= limit:
            break

    return _summarize_same_repo_precedent(repo_name or normalized_repo, matched_cycles)


def render_same_repo_precedent_text(same_repo_precedent: dict[str, Any] | None) -> str:
    if not same_repo_precedent:
        return ""
    return _normalize_text(str(same_repo_precedent.get("detail", "")))


def _review_entries(behavioral_context: BehavioralContext | None) -> list[dict[str, str]]:
    if not behavioral_context:
        return []

    entries: list[dict[str, str]] = []
    for entry in behavioral_context.contexts:
        ctx = entry.context.lower()
        if ctx in _REVIEW_CONTEXT_KEYS or "review" in ctx or "technical" in ctx:
            detail_parts = [entry.summary]
            if entry.behaviors:
                detail_parts.append("; ".join(entry.behaviors[:3]))
            if entry.communication_style:
                detail_parts.append(entry.communication_style)
            if entry.decision_style:
                detail_parts.append(entry.decision_style)
            if entry.motivators:
                detail_parts.append(f"motivators: {', '.join(entry.motivators[:3])}")
            if entry.stressors:
                detail_parts.append(f"stressors: {', '.join(entry.stressors[:3])}")
            if entry.evidence:
                detail_parts.append(f"evidence: {'; '.join(entry.evidence[:2])}")
            entries.append({"context": entry.context, "detail": " ".join(detail_parts)})
    return entries


def _audience_or_relationship_context_entries(
    behavioral_context: BehavioralContext | None,
    author_model: str,
    relationship_context: ReviewRelationshipContextV1 | None = None,
) -> list[dict[str, str]]:
    if not behavioral_context:
        return []

    relationship_terms = _relationship_terms_for_context(author_model, relationship_context)
    audience_terms = _audience_terms_for_context(author_model, relationship_context)
    entries: list[dict[str, str]] = []
    for entry in behavioral_context.contexts:
        context_text = " ".join(
            [
                entry.context,
                entry.summary,
                " ".join(entry.behaviors),
                entry.communication_style or "",
                entry.decision_style or "",
                " ".join(entry.evidence),
            ]
        ).lower()
        relationship_match = _contains_any(context_text, relationship_terms)
        audience_match = _contains_any(context_text, audience_terms)
        if not relationship_match and not audience_match:
            continue

        markers: list[str] = []
        if author_model != "unknown" and relationship_match:
            markers.append(f"relationship={author_model}")
        elif (
            relationship_context
            and relationship_context.data_confidence != "unknown"
            and relationship_match
        ):
            markers.append(
                f"relationship={relationship_context.reviewer_author_relationship}"
            )
        if audience_match:
            markers.append("audience-context")

        detail_parts = [entry.summary]
        if entry.behaviors:
            detail_parts.append("; ".join(entry.behaviors[:3]))
        if entry.communication_style:
            detail_parts.append(entry.communication_style)
        if entry.decision_style:
            detail_parts.append(entry.decision_style)
        if entry.evidence:
            detail_parts.append(f"evidence: {'; '.join(entry.evidence[:2])}")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        entries.append(
            {
                "context": entry.context,
                "detail": f"{entry.context}{marker_text}: {' '.join(detail_parts)}",
            }
        )
    return entries[:4]


def _principle_entries(mini: Any, request_text: str) -> list[dict[str, Any]]:
    raw = getattr(mini, "principles_json", None)
    if not isinstance(raw, dict):
        return []
    principles = raw.get("principles", [])
    if not isinstance(principles, list):
        return []

    keywords = set(_tokenize(request_text))
    rows: list[dict[str, Any]] = []
    for principle in principles:
        if not isinstance(principle, dict):
            continue
        trigger = _normalize_text(str(principle.get("trigger", "")))
        action = _normalize_text(str(principle.get("action", "")))
        value = _normalize_text(str(principle.get("value", "")))
        if not (trigger or action or value):
            continue
        intensity_raw = principle.get("intensity", 5)
        try:
            intensity = float(intensity_raw)
        except (TypeError, ValueError):
            intensity = 5.0
        evidence = principle.get("evidence", [])
        evidence_count = len(evidence) if isinstance(evidence, list) else 0

        detail = (
            f"principle: when {trigger} -> {action} "
            f"(value: {value}; intensity: {intensity:.2f}; evidence_count: {evidence_count})"
        )
        match_text = f"{trigger} {action} {value}".lower()
        match_score = sum(1 for keyword in keywords if keyword in match_text)

        rows.append(
            {
                "detail": detail,
                "match_score": match_score,
                "intensity": intensity,
                "evidence_count": evidence_count,
            }
        )

    rows.sort(
        key=lambda item: (
            item["match_score"],
            item["intensity"],
            item["evidence_count"],
        ),
        reverse=True,
    )
    return rows[:3]


def _review_policy_text(
    behavioral_context: BehavioralContext | None,
    motivations: MotivationsProfile | None,
    evidence_pool: list[ReviewPredictionEvidenceV1],
) -> str:
    parts: list[str] = []

    if behavioral_context:
        if behavioral_context.summary:
            parts.append(behavioral_context.summary)
        for entry in _review_entries(behavioral_context):
            parts.append(entry["detail"])

    if motivations:
        if motivations.summary:
            parts.append(motivations.summary)
        parts.extend(motivation.value for motivation in motivations.motivations[:4])
        parts.extend(
            f"{chain.implied_framework} {chain.observed_behavior}"
            for chain in motivations.motivation_chains[:3]
        )

    parts.extend(item.detail for item in evidence_pool[:4])
    return " ".join(part for part in parts if part).lower()


def _resolve_delivery_context(body: ArtifactReviewRequestBaseV1) -> tuple[str, str | None]:
    if body.delivery_context != "normal":
        return body.delivery_context, f"explicit {body.delivery_context} delivery context"

    request_text = _build_request_text(body).lower()
    if _contains_any(request_text, _INCIDENT_CONTEXT_KEYWORDS):
        return "incident", "request reads like incident recovery work"
    if _contains_any(request_text, _HOTFIX_CONTEXT_KEYWORDS):
        return "hotfix", "request reads like a hotfix path"
    if _contains_any(request_text, _EXPLORATORY_CONTEXT_KEYWORDS):
        return "exploratory", "request reads like exploratory or draft work"
    return "normal", None


def _infer_repo_context(repo_name: str | None) -> str:
    normalized = _normalize_repo_name(repo_name)
    if not normalized:
        return "standard"

    repo_token = normalized.split("/", 1)[-1]
    tokens = set(repo_token.split("-")) | set(normalized.split("/"))
    if _REPO_CONTEXT_CRITICAL_TOKENS.intersection(tokens):
        return "critical"
    if _REPO_CONTEXT_PLATFORM_TOKENS.intersection(tokens):
        return "platform"
    return "standard"


def _relationship_context_from_author_model(author_model: str) -> ReviewRelationshipContextV1:
    if author_model == "trusted_peer":
        return ReviewRelationshipContextV1(
            reviewer_author_relationship="trusted_peer",
            trust_level="high",
            mentorship_context="peer",
            data_confidence="derived",
            rationale="Derived only from explicit author_model=trusted_peer; team/channel/ownership remain unknown.",
        )
    if author_model == "junior_peer":
        return ReviewRelationshipContextV1(
            reviewer_author_relationship="junior_mentorship",
            mentorship_context="reviewer_mentors_author",
            audience_sensitivity="high",
            data_confidence="derived",
            rationale="Derived only from explicit author_model=junior_peer; trust/team/channel/ownership remain unknown.",
        )
    if author_model == "senior_peer":
        return ReviewRelationshipContextV1(
            reviewer_author_relationship="senior_peer",
            mentorship_context="peer",
            data_confidence="derived",
            rationale="Derived only from explicit author_model=senior_peer; trust/team/channel/ownership remain unknown.",
        )
    return ReviewRelationshipContextV1()


def _resolve_relationship_context(body: ArtifactReviewRequestBaseV1) -> ReviewRelationshipContextV1:
    if body.relationship_context is not None:
        context = body.relationship_context.model_copy(deep=True)
        if context.data_confidence == "unknown":
            context.data_confidence = "explicit"
        if not context.rationale or context.rationale.startswith("Relationship/team context unknown"):
            context.rationale = "Explicit relationship_context supplied on review request."
        return ReviewRelationshipContextV1.model_validate(context.model_dump())
    return _relationship_context_from_author_model(body.author_model)


def _is_junior_mentorship(
    relationship_context: ReviewRelationshipContextV1,
    author_model: str,
) -> bool:
    return (
        relationship_context.reviewer_author_relationship == "junior_mentorship"
        or relationship_context.mentorship_context == "reviewer_mentors_author"
        or author_model == "junior_peer"
    )


def _is_trusted_peer(
    relationship_context: ReviewRelationshipContextV1,
    author_model: str,
) -> bool:
    return (
        relationship_context.reviewer_author_relationship == "trusted_peer"
        or relationship_context.trust_level == "high"
        or author_model == "trusted_peer"
    )


def _is_senior_peer(
    relationship_context: ReviewRelationshipContextV1,
    author_model: str,
) -> bool:
    return relationship_context.reviewer_author_relationship == "senior_peer" or author_model == "senior_peer"


def _is_public_sensitive_context(relationship_context: ReviewRelationshipContextV1) -> bool:
    return (
        relationship_context.channel == "public_review"
        and (
            relationship_context.audience_sensitivity == "high"
            or relationship_context.team_alignment in {"cross_team", "external"}
            or relationship_context.reviewer_author_relationship == "cross_team_partner"
        )
    )


def _build_router_signals(
    *,
    author_model: str,
    context: str,
    strictness: str,
    repo_context: str,
    relationship_context: ReviewRelationshipContextV1,
    same_repo_precedent: dict[str, Any] | None,
) -> tuple[list[str], list[str], list[str], float, list[str]]:
    say = set(_DELIVERY_BUCKETS)
    suppress: set[str] = set()
    defer: set[str] = set()
    rationale_parts: list[str] = []

    precedent_focuses = set((same_repo_precedent or {}).get("focuses", []))
    precedent_count = int((same_repo_precedent or {}).get("cycle_count", 0))
    request_change_precedent_count = int(
        (same_repo_precedent or {}).get("approval_counts", {}).get("request_changes", 0)
    )

    risk_threshold = _STRICTNESS_RISK_THRESHOLD.get(strictness, 0.65)

    if context in {"hotfix", "incident"}:
        defer.update({"non_blocking", "questions", "positive"})
        risk_threshold = min(0.95, risk_threshold + 0.08)
        rationale_parts.append(f"{context} context narrows expression to high-risk blockers and blocking questions.")
    elif context == "exploratory":
        defer.update({"positive"})
        rationale_parts.append("exploratory mode keeps polish deferred while preserving risk escalation.")

    if _is_junior_mentorship(relationship_context, author_model):
        if strictness != "high":
            defer.add("non_blocking")
        rationale_parts.append("junior/mentorship context favors coaching with lower-noise delivery.")
    elif _is_trusted_peer(relationship_context, author_model):
        defer.add("non_blocking")
        risk_threshold = min(0.95, risk_threshold + 0.02)
        rationale_parts.append("trusted-peer context steers toward suppressing low-value nits.")

    if _is_public_sensitive_context(relationship_context):
        defer.update({"non_blocking", "positive"})
        risk_threshold = min(0.95, risk_threshold + 0.05)
        rationale_parts.append("public or cross-team audience sensitivity narrows expressed feedback.")

    if relationship_context.team_alignment in {"cross_team", "external"}:
        defer.add("non_blocking")
        say.add("questions")
        rationale_parts.append("cross-team context keeps expressed feedback factual and question-oriented.")

    if relationship_context.repo_ownership in {"reviewer_owned", "shared"}:
        say.add("questions")
        risk_threshold = max(0.0, risk_threshold - 0.02)
        rationale_parts.append("reviewer/shared repo ownership keeps ownership-sensitive risks explicit.")
    elif relationship_context.repo_ownership == "author_owned":
        defer.add("non_blocking")
        rationale_parts.append("author-owned repo context avoids over-expressing local preference nits.")

    if repo_context == "critical":
        say.add("questions")
        risk_threshold = max(0.0, risk_threshold - 0.03)
        rationale_parts.append("critical repo/org context keeps risk questions and blockers explicit.")
    elif repo_context == "platform":
        defer.update({"positive"})
        rationale_parts.append("platform-wide changes usually prioritize blockers over praise.")

    if precedent_count and request_change_precedent_count >= max(2, precedent_count // 2):
        if "rollout" in precedent_focuses or "tests" in precedent_focuses:
            say.add("questions")
            rationale_parts.append(
                "recent same-repo request-change precedent keeps questions and tests/rollout follow-ups in line."
            )
        if request_change_precedent_count >= precedent_count:
            risk_threshold = max(0.0, risk_threshold - 0.03)

    if strictness == "high" and _is_senior_peer(relationship_context, author_model):
        risk_threshold = max(0.0, risk_threshold - 0.02)
        rationale_parts.append("senior-peer delivery tolerates a lower say threshold for actionable risks.")

    if relationship_context.data_confidence == "unknown":
        rationale_parts.append(
            "relationship/team context unknown; no relationship-specific assumptions applied."
        )

    if not rationale_parts:
        rationale_parts.append("default deterministic router keeps standard private-to-expressed mapping.")

    return (
        sorted(say),
        sorted(suppress),
        sorted(defer),
        round(risk_threshold, 2),
        rationale_parts,
    )


def _route_assessment_bucket(
    policy: ReviewPredictionDeliveryPolicyV1,
    bucket: str,
    signals: list[ReviewPredictionSignalV1],
) -> list[ReviewPredictionSignalV1]:
    if bucket not in set(policy.say):
        return []
    if bucket in set(policy.defer) or bucket in set(policy.suppress):
        return []
    if bucket == "blocking":
        return list(signals)
    return [signal for signal in signals if signal.confidence >= policy.risk_threshold]


def _build_evidence_pool(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
    same_repo_precedent: dict[str, Any] | None = None,
    framework_signals: list[ReviewPredictionFrameworkSignalV1] | None = None,
    relationship_context: ReviewRelationshipContextV1 | None = None,
) -> list[ReviewPredictionEvidenceV1]:
    request_text = _build_request_text(body)
    behavioral_context = _parse_behavioral_context(getattr(mini, "behavioral_context_json", None))
    motivations = _parse_motivations(getattr(mini, "motivations_json", None))

    evidence: list[ReviewPredictionEvidenceV1] = []

    review_entries = _review_entries(behavioral_context)
    audience_entries = _audience_or_relationship_context_entries(
        behavioral_context,
        body.author_model,
        relationship_context,
    )
    for entry in _dedupe_context_entries([*audience_entries, *review_entries])[:6]:
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="behavioral_context",
                detail=f'{entry["context"]}: {entry["detail"][:240]}',
            )
        )

    precedent_text = render_same_repo_precedent_text(same_repo_precedent)
    if precedent_text:
        evidence.append(ReviewPredictionEvidenceV1(source="evidence", detail=precedent_text[:240]))

    if motivations and motivations.summary:
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="motivations",
                detail=motivations.summary[:240],
            )
        )

    for entry in _principle_entries(mini, request_text):
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="principles",
                detail=entry["detail"][:300],
            )
        )

    for signal in (framework_signals or [])[:3]:
        framework_detail = (
            f"framework_id={signal.framework_id}; {signal.name}: {signal.summary} "
            f"(confidence: {signal.confidence:.2f}; reason: {signal.reason}; "
            f"temporal_stability_bonus: {signal.temporal_stability_bonus:.2f}; "
            f"scope_match_boost: {signal.scope_match_boost:.2f})"
        )
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="principles",
                detail=framework_detail[:300],
            )
        )

    memory_content = _normalize_text(getattr(mini, "memory_content", None))
    for snippet in _keyword_search_snippets(memory_content, request_text, max_results=2):
        evidence.append(ReviewPredictionEvidenceV1(source="memory", detail=snippet))

    evidence_cache = _normalize_text(getattr(mini, "evidence_cache", None))
    for snippet in _keyword_search_snippets(evidence_cache, request_text, max_results=2):
        evidence.append(ReviewPredictionEvidenceV1(source="evidence", detail=snippet))

    if body.title:
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="input",
                detail=f"{_artifact_kind_label(body).title()} title: {body.title[:240]}",
            )
        )

    deduped: list[ReviewPredictionEvidenceV1] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (item.source, item.detail)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _review_fidelity_evidence_counts(
    mini: Any,
    same_repo_precedent: dict[str, Any] | None = None,
) -> dict[str, int]:
    behavioral_context = _parse_behavioral_context(getattr(mini, "behavioral_context_json", None))
    motivations = _parse_motivations(getattr(mini, "motivations_json", None))
    principles_raw = getattr(mini, "principles_json", None)
    principles_count = 0
    if isinstance(principles_raw, dict):
        principles = principles_raw.get("principles")
        if isinstance(principles, list):
            principles_count = len([item for item in principles if isinstance(item, dict)])

    memory_content = _normalize_text(getattr(mini, "memory_content", None))
    evidence_cache = _normalize_text(getattr(mini, "evidence_cache", None))

    return {
        "decision_frameworks": len(_extract_decision_frameworks(principles_raw)),
        "principles": principles_count,
        "review_behavior": len(_review_entries(behavioral_context)),
        "motivations": (
            len(motivations.motivations) + len(motivations.motivation_chains)
            if motivations
            else 0
        ),
        "memory": 1 if memory_content else 0,
        "evidence": 1 if evidence_cache else 0,
        "same_repo_precedent": int((same_repo_precedent or {}).get("cycle_count", 0)),
    }


def review_prediction_insufficiency_reason(
    mini: Any,
    same_repo_precedent: dict[str, Any] | None = None,
) -> str | None:
    counts = _review_fidelity_evidence_counts(mini, same_repo_precedent)
    if sum(counts.values()) > 0:
        return None
    return (
        "insufficient review-fidelity evidence: no decision frameworks, principles, "
        "review behavior, motivations, memory, raw evidence, or same-repo review "
        "precedent are available"
    )


def _dedupe_context_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry.get("context", ""), entry.get("detail", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _infer_recency_score(detail: str) -> float:
    lower_detail = detail.lower()
    if any(keyword in lower_detail for keyword in _RECENCY_HINT_KEYWORDS):
        return 0.95

    years = [int(match) for match in re.findall(r"\b(20\d{2})\b", detail)]
    if not years:
        return 0.5

    newest_year = max(years)
    age = max(0, datetime.now(UTC).year - newest_year)
    if age == 0:
        return 0.95
    if age == 1:
        return 0.85
    if age == 2:
        return 0.75
    if age == 3:
        return 0.65
    return 0.45


def _stability_components(
    item: ReviewPredictionEvidenceV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
) -> tuple[float, float, float]:
    # 1) Principle frequency: prioritize repeated framework rules over one-off comments.
    principle_matches = 0
    for candidate in evidence_pool:
        if candidate.source != "principles":
            continue
        lower_detail = candidate.detail.lower()
        if any(keyword in lower_detail for keyword in keywords):
            principle_matches += 1
    principle_frequency = min(principle_matches / 3.0, 1.0)
    if item.source == "principles":
        evidence_count_match = re.search(r"evidence_count:\s*(\d+)", item.detail.lower())
        if evidence_count_match:
            evidence_count = int(evidence_count_match.group(1))
            principle_frequency = max(principle_frequency, min(evidence_count / 3.0, 1.0))
    else:
        principle_frequency *= 0.4

    # 2) Cross-context consistency: reward signals echoed across multiple evidence types.
    matching_sources = {
        candidate.source
        for candidate in evidence_pool
        if any(keyword in candidate.detail.lower() for keyword in keywords)
    }
    cross_context_consistency = min(len(matching_sources) / 4.0, 1.0)

    # 3) Source confidence: durable source reliability prior.
    source_confidence = _SOURCE_CONFIDENCE.get(item.source, 0.5)

    return principle_frequency, cross_context_consistency, source_confidence


def _relationship_fit(
    detail: str,
    author_model: str,
    relationship_context: ReviewRelationshipContextV1 | None,
) -> float:
    if (
        author_model == "unknown"
        and (
            relationship_context is None
            or relationship_context.data_confidence == "unknown"
        )
    ):
        return 0.0
    terms = _relationship_terms_for_context(author_model, relationship_context)
    if not terms:
        return 0.0
    return 1.0 if _contains_any(detail, terms) else 0.0


def _audience_fit(
    detail: str,
    author_model: str,
    relationship_context: ReviewRelationshipContextV1 | None,
) -> float:
    terms = _audience_terms_for_context(author_model, relationship_context)
    if not terms:
        return 0.0
    return 1.0 if _contains_any(detail, terms) else 0.0


def _framework_relevance_score(
    item: ReviewPredictionEvidenceV1,
    keywords: set[str],
) -> float:
    lower_detail = item.detail.lower()
    lexical = sum(1 for keyword in keywords if keyword in lower_detail)
    if item.source == "principles" and "framework_id=" in lower_detail:
        return min(1.0, 0.78 + min(lexical, 3) * 0.06)
    if item.source == "principles":
        return min(0.9, 0.62 + min(lexical, 3) * 0.06)
    if item.source in {"behavioral_context", "motivations"} and lexical > 0:
        return min(0.65, 0.35 + lexical * 0.08)
    return min(0.45, lexical * 0.08)


def _recent_local_context_score(item: ReviewPredictionEvidenceV1) -> float:
    detail = item.detail.lower()
    recency = _infer_recency_score(item.detail)
    local_context = (
        "same-repo" in detail
        or "scope_match_boost:" in detail
        or item.source == "evidence"
        or any(keyword in detail for keyword in _RECENCY_HINT_KEYWORDS)
    )
    if not local_context:
        return recency * 0.25
    return recency


def _ranking_signal(
    name: Literal[
        "lexical_relevance",
        "durable_framework",
        "recent_local_context",
        "framework_relevance",
        "relationship_context",
        "audience_context",
    ],
    value: float,
    reason: str,
) -> ReviewPredictionEvidenceRankingSignalV1:
    return ReviewPredictionEvidenceRankingSignalV1(
        name=name,
        value=round(_coerce_confidence(value), 3),
        reason=reason,
    )


def _rank_evidence_item(
    item: ReviewPredictionEvidenceV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
    body: ArtifactReviewRequestBaseV1,
) -> tuple[float, int, ReviewPredictionEvidenceV1]:
    resolved_relationship_context = _resolve_relationship_context(body)
    lower_detail = item.detail.lower()
    lexical = sum(1 for keyword in keywords if keyword in lower_detail)
    lexical_relevance = min(lexical / 4.0, 1.0)
    recent_local_context = _recent_local_context_score(item)
    principle_frequency, cross_context_consistency, source_confidence = _stability_components(
        item,
        evidence_pool,
        keywords,
    )
    durable_framework = (
        (principle_frequency * 0.35)
        + (cross_context_consistency * 0.30)
        + (source_confidence * 0.35)
    )
    framework_relevance = _framework_relevance_score(item, keywords)
    relationship_context = _relationship_fit(
        lower_detail,
        body.author_model,
        resolved_relationship_context,
    )
    audience_context = _audience_fit(
        lower_detail,
        body.author_model,
        resolved_relationship_context,
    )

    final_score = (
        (durable_framework * 0.30)
        + (recent_local_context * 0.18)
        + (framework_relevance * 0.18)
        + (lexical_relevance * 0.16)
        + (relationship_context * 0.10)
        + (audience_context * 0.08)
    )

    relationship_reason = (
        f"Matched explicit author_model={body.author_model} relationship markers."
        if relationship_context
        else (
            "Author relationship is unknown, so no relationship fit was inferred."
            if resolved_relationship_context.data_confidence == "unknown"
            else "No explicit reviewer-author relationship markers matched this evidence."
        )
    )
    audience_reason = (
        "Matched audience markers for this review context."
        if audience_context
        else "No audience-specific marker matched; treated as neutral."
    )
    ranked_item = item.model_copy(
        update={
            "ranking_signals": [
                _ranking_signal(
                    "lexical_relevance",
                    lexical_relevance,
                    f"Matched {lexical} request term(s) against the evidence detail.",
                ),
                _ranking_signal(
                    "durable_framework",
                    durable_framework,
                    "Combines principle frequency, cross-source consistency, and source reliability.",
                ),
                _ranking_signal(
                    "recent_local_context",
                    recent_local_context,
                    "Rewards recent or same-repo local context without letting it overwhelm durable frameworks.",
                ),
                _ranking_signal(
                    "framework_relevance",
                    framework_relevance,
                    "Uses extracted principles/framework entries and request overlap as typed framework signal.",
                ),
                _ranking_signal(
                    "relationship_context",
                    relationship_context,
                    relationship_reason,
                ),
                _ranking_signal(
                    "audience_context",
                    audience_context,
                    audience_reason,
                ),
            ]
        }
    )

    return final_score, lexical, ranked_item


def _pick_evidence(
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
    body: ArtifactReviewRequestBaseV1,
    max_items: int = 2,
) -> list[ReviewPredictionEvidenceV1]:
    if not evidence_pool:
        return []

    ranked: list[tuple[float, int, int, ReviewPredictionEvidenceV1]] = []
    for item in evidence_pool:
        blended, lexical, ranked_item = _rank_evidence_item(item, evidence_pool, keywords, body)
        context_signal = max(
            (
                signal.value
                for signal in ranked_item.ranking_signals
                if signal.name in {"relationship_context", "audience_context"}
            ),
            default=0.0,
        )
        ranked.append((blended, lexical, int(context_signal > 0.0), ranked_item))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    selected = [item for _blend, score, _context, item in ranked if score > 0][:max_items]
    if selected:
        return selected
    return [item for _blend, _score, _context, item in ranked[:max_items]]


def _specificity_from_evidence(
    evidence: list[ReviewPredictionEvidenceV1],
) -> str:
    sources = {item.source for item in evidence}
    if "principles" in sources:
        return "framework_specific"
    if sources & {"behavioral_context", "motivations", "memory", "evidence"}:
        return "evidence_backed"
    if sources == {"input"}:
        return "request_context_only"
    return "insufficient"


def _contains_any(text: str, keywords: set[str]) -> bool:
    lower_text = text.lower()
    return any(keyword in lower_text for keyword in keywords)


def _has_matching_file(paths: list[str], patterns: tuple[str, ...]) -> bool:
    lowered = [path.lower() for path in paths]
    return any(pattern in path for path in lowered for pattern in patterns)


def _derive_delivery_policy(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    same_repo_precedent: dict[str, Any] | None = None,
    relationship_context: ReviewRelationshipContextV1 | None = None,
) -> ReviewPredictionDeliveryPolicyV1:
    relationship_context = relationship_context or _resolve_relationship_context(body)
    behavioral_context = _parse_behavioral_context(getattr(mini, "behavioral_context_json", None))
    values = _parse_values(getattr(mini, "values_json", None))
    code_quality = _engineering_value(values, "Code Quality")
    directness = _engineering_value(values, "Directness")
    pragmatism = _engineering_value(values, "Pragmatism")
    motivations = _parse_motivations(getattr(mini, "motivations_json", None))
    resolved_context, inferred_context_rationale = _resolve_delivery_context(body)
    review_policy_text = _review_policy_text(behavioral_context, motivations, evidence_pool)
    motivation_text = " ".join(
        motivation.value.lower() for motivation in (motivations.motivations if motivations else [])
    )
    has_direct_review_signal = _contains_any(review_policy_text, _DIRECT_REVIEW_KEYWORDS)
    has_high_bar_signal = _contains_any(review_policy_text, _HIGH_BAR_KEYWORDS)
    has_noise_shield_signal = _contains_any(review_policy_text, _NOISE_SHIELD_KEYWORDS)
    has_teaching_signal = _contains_any(
        f"{review_policy_text} {motivation_text}", _TEACHING_KEYWORDS
    )

    score = 1
    rationale_parts: list[str] = []
    precedent_focuses = set((same_repo_precedent or {}).get("focuses", []))
    request_change_precedent_count = (
        (same_repo_precedent or {}).get("approval_counts", {}).get("request_changes", 0)
    )
    same_repo_precedent_count = (same_repo_precedent or {}).get("cycle_count", 0)

    if inferred_context_rationale:
        rationale_parts.append(inferred_context_rationale)
    if has_high_bar_signal:
        score += 1
        rationale_parts.append("review evidence emphasizes tests, boundaries, or rollout safety")
    elif code_quality >= 7.0:
        score += 1
        rationale_parts.append("strong code-quality signal")
    if has_direct_review_signal:
        score += 1
        rationale_parts.append("review context reads as direct and specific")
    elif directness >= 7.0:
        score += 1
        rationale_parts.append("direct review style")
    if pragmatism >= 7.0 and resolved_context in {"hotfix", "incident", "exploratory"}:
        score -= 1
        rationale_parts.append("pragmatic under delivery pressure")
    if resolved_context in {"hotfix", "incident"}:
        score -= 1
        rationale_parts.append(f"{resolved_context} context reduces review surface")
    elif resolved_context == "exploratory":
        score -= 1
        rationale_parts.append("exploratory work lowers polish expectations")
    if _is_senior_peer(relationship_context, body.author_model):
        score += 1
        rationale_parts.append("more willing to be direct with senior peers")
    elif _is_junior_mentorship(relationship_context, body.author_model):
        score -= 1
        rationale_parts.append("junior/mentorship relationship shifts toward coaching")
    elif _is_trusted_peer(relationship_context, body.author_model) and (
        has_noise_shield_signal or pragmatism >= 7.0
    ):
        score -= 1
        rationale_parts.append("trusted-peer context narrows feedback to high-signal issues")
    if relationship_context.repo_ownership in {"reviewer_owned", "shared"}:
        score += 1
        rationale_parts.append("reviewer/shared repo ownership raises expressed risk sensitivity")
    elif relationship_context.repo_ownership == "author_owned":
        score -= 1
        rationale_parts.append("author-owned repo context lowers preference-policing strictness")
    if _is_public_sensitive_context(relationship_context):
        score -= 1
        rationale_parts.append("public/cross-team audience sensitivity softens non-blocking delivery")
    if precedent_focuses:
        rationale_parts.append(
            f"same-repo review precedent reinforces focus on {', '.join(sorted(precedent_focuses))}"
        )
    if same_repo_precedent_count and request_change_precedent_count >= max(2, same_repo_precedent_count // 2):
        score += 1
        rationale_parts.append("recent same-repo review cycles often landed as request-changes")

    strictness = "medium"
    if score <= 0:
        strictness = "low"
    elif score >= 3:
        strictness = "high"

    if strictness == "high" and _is_junior_mentorship(relationship_context, body.author_model):
        strictness = "medium"
        rationale_parts.append("junior/mentorship delivery keeps strictness below maximum")
    if strictness == "high" and resolved_context == "exploratory":
        strictness = "medium"
        rationale_parts.append("exploratory context avoids production-grade strictness")

    teaching_mode = _is_junior_mentorship(relationship_context, body.author_model) or (
        resolved_context not in {"hotfix", "incident"}
        and (has_teaching_signal or resolved_context == "exploratory")
    )
    shield_author_from_noise = resolved_context in {"hotfix", "incident", "exploratory"} or (
        (
            _is_trusted_peer(relationship_context, body.author_model)
            or _is_junior_mentorship(relationship_context, body.author_model)
        )
        and strictness != "high"
    )
    if _is_public_sensitive_context(relationship_context):
        shield_author_from_noise = True
    if has_noise_shield_signal:
        shield_author_from_noise = True
        rationale_parts.append("stored review context shows low tolerance for noisy churn")
    repo_context = _infer_repo_context(body.repo_name)
    (
        say,
        suppress,
        defer,
        risk_threshold,
        router_rationale,
    ) = _build_router_signals(
        author_model=body.author_model,
        context=resolved_context,
        strictness=strictness,
        repo_context=repo_context,
        relationship_context=relationship_context,
        same_repo_precedent=same_repo_precedent,
    )
    rationale_parts.extend(router_rationale)
    rationale_parts.append(relationship_context.rationale)

    if not rationale_parts and evidence_pool:
        rationale_parts.append("using stored review-context evidence")
    if not rationale_parts:
        rationale_parts.append("falling back to neutral review policy defaults")

    return ReviewPredictionDeliveryPolicyV1(
        author_model=body.author_model,
        context=resolved_context,
        relationship_context=relationship_context,
        strictness=strictness,
        teaching_mode=teaching_mode,
        shield_author_from_noise=shield_author_from_noise,
        say=say,
        suppress=suppress,
        defer=defer,
        risk_threshold=risk_threshold,
        rationale=", ".join(rationale_parts),
    )


def _make_signal(
    key: str,
    summary: str,
    rationale: str,
    confidence: float,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
    body: ArtifactReviewRequestBaseV1,
) -> ReviewPredictionSignalV1:
    evidence = _pick_evidence(evidence_pool, keywords, body)
    return ReviewPredictionSignalV1(
        key=key,
        summary=summary,
        rationale=rationale,
        confidence=confidence,
        specificity=_specificity_from_evidence(evidence),
        evidence=evidence,
    )


def _build_private_assessment(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
    policy: ReviewPredictionDeliveryPolicyV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    same_repo_precedent: dict[str, Any] | None = None,
) -> ReviewPredictionPrivateAssessmentV1:
    request_text = _build_request_text(body)
    request_text_lower = request_text.lower()
    delivery_context = policy.context
    values = _parse_values(getattr(mini, "values_json", None))
    code_quality = _engineering_value(values, "Code Quality")
    has_tests = _contains_any(request_text_lower, _TEST_KEYWORDS) or _has_matching_file(
        body.changed_files, ("test", "spec")
    )
    has_rollout = _contains_any(request_text_lower, _ROLLOUT_KEYWORDS)
    has_docs = _contains_any(request_text_lower, _DOC_KEYWORDS) or _has_matching_file(
        body.changed_files, ("readme", "docs/")
    )
    has_migration = _contains_any(request_text_lower, {"migration", "backfill", "alembic"}) or (
        _has_matching_file(body.changed_files, ("migration", "alembic"))
    )
    precedent_focus_counts = (same_repo_precedent or {}).get("focus_counts", {})
    precedent_focuses = set((same_repo_precedent or {}).get("focuses", []))
    precedent_requires_tests = precedent_focus_counts.get("tests", 0) >= 2
    precedent_requires_rollout = precedent_focus_counts.get("rollout", 0) >= 2

    blocking_issues: list[ReviewPredictionSignalV1] = []
    non_blocking_issues: list[ReviewPredictionSignalV1] = []
    open_questions: list[ReviewPredictionSignalV1] = []
    positive_signals: list[ReviewPredictionSignalV1] = []

    risk_keywords_present = {
        keyword for keyword in _RISK_KEYWORDS if keyword in request_text_lower
    }

    if any(keyword in request_text_lower for keyword in {"auth", "authorization", "permission", "secret", "token", "oauth", "jwt"}):
        blocking_issues.append(
            _make_signal(
                key="auth-boundary",
                summary="Likely to scrutinize auth and permission boundaries before approving.",
                rationale="Changes touching credentials or authorization usually read as high-severity review territory.",
                confidence=0.82,
                evidence_pool=evidence_pool,
                keywords={"auth", "permission", "security", "token"},
                body=body,
            )
        )

    if any(keyword in request_text_lower for keyword in {"database", "migration", "schema", "sql", "contract"}):
        if not has_migration:
            blocking_issues.append(
                _make_signal(
                    key="migration-plan",
                    summary="Would likely block until the migration or compatibility plan is explicit.",
                    rationale="Schema and contract changes usually need rollout, migration, or backward-compatibility coverage.",
                    confidence=0.8,
                    evidence_pool=evidence_pool,
                    keywords={"migration", "schema", "database", "contract"},
                    body=body,
                )
            )
        else:
            positive_signals.append(
                _make_signal(
                    key="migration-awareness",
                    summary="The change already signals migration or compatibility awareness.",
                    rationale="Explicit migration notes reduce ambiguity on risky data-shape changes.",
                    confidence=0.71,
                    evidence_pool=evidence_pool,
                    keywords={"migration", "schema", "database"},
                    body=body,
                )
            )

    if any(keyword in request_text_lower for keyword in {"cache", "async", "queue", "worker", "concurrency", "retry", "timeout"}):
        blocking_issues.append(
            _make_signal(
                key="runtime-behavior",
                summary="Would likely pressure-test runtime behavior, retries, and failure modes.",
                rationale="Asynchronous or stateful changes often hide the sort of edge cases reviewers escalate quickly.",
                confidence=0.77,
                evidence_pool=evidence_pool,
                keywords={"cache", "async", "queue", "worker", "retry", "timeout"},
                body=body,
            )
        )

    if risk_keywords_present and not has_tests:
        target = (
            blocking_issues
            if policy.strictness == "high" or code_quality >= 7.0 or precedent_requires_tests
            else open_questions
        )
        rationale = (
            "Risky behavior changes without explicit tests are a recurring review trigger for quality-focused reviewers."
        )
        if precedent_requires_tests:
            rationale = _append_sentence(
                rationale,
                "Recent same-repo review cycles repeatedly centered tests before merge.",
            )
        target.append(
            _make_signal(
                key="test-coverage",
                summary="Would likely ask for stronger test coverage around the risky path.",
                rationale=rationale,
                confidence=0.78 if target is blocking_issues else 0.68,
                evidence_pool=evidence_pool,
                keywords={"test", "coverage", "review", "quality"},
                body=body,
            )
        )
    elif has_tests:
        positive_signals.append(
            _make_signal(
                key="tests-present",
                summary="The change already mentions tests or coverage work.",
                rationale="Explicit test coverage lowers the probability of a hard block.",
                confidence=0.72,
                evidence_pool=evidence_pool,
                keywords={"test", "coverage"},
                body=body,
            )
        )

    if risk_keywords_present and not has_rollout and delivery_context != "exploratory":
        rollout_rationale = (
            "Risky changes are easier to ship when the blast radius and recovery path are explicit."
        )
        if precedent_requires_rollout:
            rollout_rationale = _append_sentence(
                rollout_rationale,
                "Recent same-repo review cycles repeatedly asked for rollout or rollback posture.",
            )
        open_questions.append(
            _make_signal(
                key="rollout-safety",
                summary="Would likely ask about rollout safety, monitoring, or rollback posture.",
                rationale=rollout_rationale,
                confidence=0.66,
                evidence_pool=evidence_pool,
                keywords={"rollback", "metrics", "logging", "flag", "monitor"},
                body=body,
            )
        )
    elif has_rollout:
        positive_signals.append(
            _make_signal(
                key="rollout-awareness",
                summary="The change already mentions rollout or observability guardrails.",
                rationale="Feature flags, logging, or rollback notes usually read as good review hygiene.",
                confidence=0.67,
                evidence_pool=evidence_pool,
                keywords={"rollback", "metrics", "logging", "flag", "monitor"},
                body=body,
            )
        )

    if _contains_any(request_text_lower, {"refactor", "rename", "cleanup", "naming", "readability"}):
        non_blocking_issues.append(
            _make_signal(
                key="clarity-pass",
                summary="Could leave a non-blocking note on naming or boundary clarity.",
                rationale="Refactors and cleanup diffs often trigger clarity comments even when the core change is sound.",
                confidence=0.58,
                evidence_pool=evidence_pool,
                keywords={"clarity", "naming", "readability", "refactor"},
                body=body,
            )
        )

    if has_docs:
        positive_signals.append(
            _make_signal(
                key="docs-present",
                summary="Documentation or inline explanation is already part of the change.",
                rationale="Clear written context usually improves review throughput and reduces back-and-forth.",
                confidence=0.61,
                evidence_pool=evidence_pool,
                keywords={"docs", "documentation", "readme", "comment"},
                body=body,
            )
        )
    if has_tests and "tests" in precedent_focuses:
        positive_signals.append(
            _make_signal(
                key="repo-precedent-addressed",
                summary="The change already covers a recurring same-repo review ask.",
                rationale="Recent same-repo review cycles repeatedly focused on tests, and this change already includes them.",
                confidence=0.63,
                evidence_pool=evidence_pool,
                keywords={"test", "coverage", "review"},
                body=body,
            )
        )

    evidence_bonus = min(len(evidence_pool), 4) * 0.08
    request_bonus = 0.15 if len(request_text) >= 120 else 0.05
    confidence = min(0.92, 0.2 + evidence_bonus + request_bonus)

    return ReviewPredictionPrivateAssessmentV1(
        blocking_issues=blocking_issues,
        non_blocking_issues=non_blocking_issues,
        open_questions=open_questions,
        positive_signals=positive_signals,
        confidence=round(confidence, 2),
    )


def _append_sentence(text: str, sentence: str | None) -> str:
    if not sentence:
        return text

    normalized = text.rstrip()
    if normalized and normalized[-1] not in ".!?":
        normalized = f"{normalized}."
    return f"{normalized} {sentence}".strip()


def _feedback_summary(
    approval_state: str,
    policy: ReviewPredictionDeliveryPolicyV1,
    body: ArtifactReviewRequestBaseV1,
) -> str:
    artifact_scope = _artifact_scope_label(body)
    if approval_state == "request_changes":
        if body.artifact_type == "pull_request" and policy.strictness == "high":
            summary = "Would likely request changes directly and center the review on the main merge-risk issues."
        elif body.artifact_type == "pull_request" and policy.strictness == "low":
            summary = "Would likely ask for a narrow set of changes before merge."
        elif body.artifact_type == "pull_request":
            summary = "Would likely ask for changes, but keep the feedback focused on the main risks."
        elif policy.strictness == "high":
            summary = (
                f"Would likely request changes directly and center the review on the main sign-off risks in the {artifact_scope}."
            )
        elif policy.strictness == "low":
            summary = f"Would likely ask for a narrow set of changes before sign-off on the {artifact_scope}."
        else:
            summary = f"Would likely ask for changes, but keep the feedback focused on the main sign-off risks in the {artifact_scope}."
    elif approval_state == "comment":
        if policy.shield_author_from_noise:
            if body.artifact_type == "pull_request":
                summary = "Would likely leave a narrow set of high-signal comments without blocking the change."
            else:
                summary = f"Would likely leave a narrow set of high-signal comments without blocking sign-off on the {artifact_scope}."
        else:
            if body.artifact_type == "pull_request":
                summary = "Would likely leave a small set of comments or questions without blocking the change."
            else:
                summary = f"Would likely leave a small set of comments or questions without blocking sign-off on the {artifact_scope}."
    elif approval_state == "approve":
        if policy.shield_author_from_noise:
            if body.artifact_type == "pull_request":
                summary = "Would likely approve without piling on extra nits."
            else:
                summary = f"Would likely give sign-off on the {artifact_scope} without piling on extra nits."
        else:
            if body.artifact_type == "pull_request":
                summary = "Would likely approve and mention the strongest positive signals."
            else:
                summary = f"Would likely give sign-off on the {artifact_scope} and mention the strongest positive signals."
    else:
        summary = "Not enough change detail to predict a confident review outcome."

    if approval_state != "uncertain":
        if policy.context in {"hotfix", "incident"}:
            summary = _append_sentence(
                summary,
                f"In this {policy.context} context, the thread would stay tightly scoped to unblock safe delivery.",
            )
        elif policy.context == "exploratory":
            summary = _append_sentence(
                summary,
                "In exploratory work, the feedback would focus on the next safe step rather than polish.",
            )

        if policy.teaching_mode:
            summary = _append_sentence(
                summary,
                "The tone would skew explanatory and coaching-oriented.",
            )
        elif policy.strictness == "high" or _is_senior_peer(
            policy.relationship_context,
            policy.author_model,
        ):
            summary = _append_sentence(
                summary,
                "The wording would likely stay pretty direct.",
            )

        if policy.shield_author_from_noise:
            summary = _append_sentence(
                summary,
                "Lower-value nits would likely stay unsaid.",
            )

    return summary


def _comment_delivery_addendum(
    signal_type: str,
    policy: ReviewPredictionDeliveryPolicyV1,
) -> str | None:
    if signal_type == "praise" and policy.teaching_mode:
        return "Would likely reinforce this habit explicitly so it sticks."
    if signal_type == "blocker":
        if policy.context in {"hotfix", "incident"}:
            return "Would likely frame it as a narrowly scoped unblocker for the current delivery pressure."
        if policy.teaching_mode:
            return "Would likely explain the tradeoff and the next fix, not just point at the problem."
        if policy.strictness == "high" or _is_senior_peer(
            policy.relationship_context,
            policy.author_model,
        ):
            return "Would likely state this pretty directly."
        return None
    if signal_type == "question":
        if policy.teaching_mode:
            return "Would likely use the question to guide the next revision step."
        if policy.context == "exploratory":
            return "Would likely keep this exploratory rather than treating it as a hard block."
        return None
    if signal_type == "note" and not policy.shield_author_from_noise:
        if policy.teaching_mode:
            return "Would likely frame it as a coaching note rather than a nit."
        if policy.strictness == "high":
            return "Would likely keep even the non-blocking note concrete and specific."
    return None


def _comment_limit(
    policy: ReviewPredictionDeliveryPolicyV1,
    signal_group: str,
) -> int:
    if signal_group == "blocking":
        if policy.context in {"hotfix", "incident"} or policy.strictness == "low":
            return 1
        return 2 if policy.strictness == "high" else 1
    if signal_group == "non_blocking":
        if policy.shield_author_from_noise:
            return 0
        return 1 if policy.teaching_mode or policy.strictness == "low" else 2
    if signal_group == "questions":
        if policy.context in {"hotfix", "incident"} and policy.strictness != "high":
            return 0
        return 1
    if signal_group == "positive":
        return 1 if policy.teaching_mode or policy.shield_author_from_noise else 2
    return 0


def _make_expressed_comment(
    signal: ReviewPredictionSignalV1,
    signal_type: str,
    disposition: str,
    policy: ReviewPredictionDeliveryPolicyV1,
) -> ReviewPredictionCommentV1:
    return ReviewPredictionCommentV1(
        type=signal_type,
        disposition=disposition,
        issue_key=signal.key,
        specificity=signal.specificity,
        summary=signal.summary,
        rationale=_append_sentence(signal.rationale, _comment_delivery_addendum(signal_type, policy)),
    )


def _expression_disposition_for_signal(
    policy: ReviewPredictionDeliveryPolicyV1,
    bucket: str,
    signal: ReviewPredictionSignalV1,
) -> tuple[str, str]:
    if bucket not in set(policy.say):
        return "suppressed", f"{bucket} is not in delivery_policy.say."
    if bucket in set(policy.suppress):
        return "suppressed", f"{bucket} is explicitly suppressed by delivery policy."
    if bucket in set(policy.defer):
        return "deferred", f"{bucket} is deferred by audience/context delivery policy."
    if bucket != "blocking" and signal.confidence < policy.risk_threshold:
        return (
            "below_threshold",
            f"signal confidence {signal.confidence:.2f} is below risk_threshold {policy.risk_threshold:.2f}.",
        )
    return "expressed", "signal crosses delivery policy and specificity thresholds."


def _build_private_expressed_deltas(
    assessment: ReviewPredictionPrivateAssessmentV1,
    policy: ReviewPredictionDeliveryPolicyV1,
) -> list[ReviewPredictionExpressionDeltaV1]:
    buckets: dict[str, list[ReviewPredictionSignalV1]] = {
        "blocking": assessment.blocking_issues,
        "non_blocking": assessment.non_blocking_issues,
        "questions": assessment.open_questions,
        "positive": assessment.positive_signals,
    }
    routed = {
        bucket: _route_assessment_bucket(policy, bucket, signals)
        for bucket, signals in buckets.items()
    }
    if routed["blocking"]:
        active_buckets = {"blocking", "non_blocking", "questions"}
    elif routed["non_blocking"] or routed["questions"]:
        active_buckets = {"non_blocking", "questions"}
    elif routed["positive"]:
        active_buckets = {"positive"}
    else:
        active_buckets = set()

    deltas: list[ReviewPredictionExpressionDeltaV1] = []
    for bucket, signals in buckets.items():
        expressed_slots = _comment_limit(policy, bucket) if bucket in active_buckets else 0
        expressed_keys = {signal.key for signal in routed[bucket][:expressed_slots]}
        for signal in signals:
            disposition, rationale = _expression_disposition_for_signal(policy, bucket, signal)
            if disposition == "expressed" and signal.key not in expressed_keys:
                disposition = "deferred"
                rationale = f"{bucket} crossed routing policy but was deferred by expressed comment limits."
            deltas.append(
                ReviewPredictionExpressionDeltaV1(
                    issue_key=signal.key,
                    private_bucket=bucket,
                    expressed_disposition=disposition,
                    specificity=signal.specificity,
                    confidence=signal.confidence,
                    rationale=rationale,
                )
            )
    return deltas


def _build_expressed_feedback(
    assessment: ReviewPredictionPrivateAssessmentV1,
    policy: ReviewPredictionDeliveryPolicyV1,
    body: ArtifactReviewRequestBaseV1,
) -> ReviewPredictionExpressedFeedbackV1:
    comments: list[ReviewPredictionCommentV1] = []
    routed_blocking = _route_assessment_bucket(policy, "blocking", assessment.blocking_issues)
    routed_non_blocking = _route_assessment_bucket(
        policy,
        "non_blocking",
        assessment.non_blocking_issues,
    )
    routed_questions = _route_assessment_bucket(policy, "questions", assessment.open_questions)
    routed_positive = _route_assessment_bucket(policy, "positive", assessment.positive_signals)

    if routed_blocking:
        approval_state = "request_changes"
        summary = _feedback_summary(approval_state, policy, body)

        surfaced_blockers = routed_blocking[: _comment_limit(policy, "blocking")]
        surfaced_non_blocking = routed_non_blocking[: _comment_limit(policy, "non_blocking")]
        surfaced_questions = routed_questions[: _comment_limit(policy, "questions")]

        for signal in surfaced_blockers:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="blocker",
                    disposition="request_changes",
                    policy=policy,
                )
            )

        if policy.teaching_mode:
            for signal in surfaced_questions:
                comments.append(
                    _make_expressed_comment(
                        signal=signal,
                        signal_type="question",
                        disposition="request_changes",
                        policy=policy,
                    )
                )
        for signal in surfaced_non_blocking:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="note",
                    disposition="comment",
                    policy=policy,
                )
            )
        if not policy.teaching_mode:
            for signal in surfaced_questions:
                comments.append(
                    _make_expressed_comment(
                        signal=signal,
                        signal_type="question",
                        disposition="comment",
                        policy=policy,
                    )
                )
    elif routed_non_blocking or routed_questions:
        approval_state = "comment"
        summary = _feedback_summary(approval_state, policy, body)
        for signal in routed_questions[: _comment_limit(policy, "questions")]:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="question",
                    disposition="comment",
                    policy=policy,
                )
            )
        for signal in routed_non_blocking[: _comment_limit(policy, "non_blocking")]:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="note",
                    disposition="comment",
                    policy=policy,
                )
            )
    elif routed_positive:
        approval_state = "approve"
        summary = _feedback_summary(approval_state, policy, body)
        for signal in routed_positive[: _comment_limit(policy, "positive")]:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="praise",
                    disposition="approve",
                    policy=policy,
                )
            )
    else:
        approval_state = "uncertain"
        summary = _feedback_summary(approval_state, policy, body)

    return ReviewPredictionExpressedFeedbackV1(
        summary=summary,
        comments=comments,
        approval_state=approval_state,
    )


def _build_artifact_review_fields(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
    *,
    same_repo_precedent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    relationship_context = _resolve_relationship_context(body)
    framework_signals, framework_temporal_balance = _build_framework_signals(mini, body)
    evidence_pool = _build_evidence_pool(
        mini,
        body,
        same_repo_precedent=same_repo_precedent,
        framework_signals=framework_signals,
        relationship_context=relationship_context,
    )
    policy = _derive_delivery_policy(
        mini,
        body,
        evidence_pool,
        same_repo_precedent=same_repo_precedent,
        relationship_context=relationship_context,
    )
    framework_conflict_resolution = _resolve_framework_conflicts(
        framework_signals,
        body=body,
        policy=policy,
    )
    assessment = _build_private_assessment(
        mini,
        body,
        policy,
        evidence_pool,
        same_repo_precedent=same_repo_precedent,
    )
    expressed_feedback = _build_expressed_feedback(assessment, policy, body)
    private_expressed_deltas = _build_private_expressed_deltas(assessment, policy)

    return {
        "reviewer_username": getattr(mini, "username", "unknown"),
        "repo_name": body.repo_name,
        "artifact_summary": ArtifactSummaryV1(
            artifact_type=body.artifact_type,
            title=body.title,
        ),
        "relationship_context": relationship_context,
        "framework_signals": framework_signals,
        "framework_conflict_resolution": framework_conflict_resolution,
        "framework_temporal_balance": framework_temporal_balance,
        "private_assessment": assessment,
        "delivery_policy": policy,
        "expressed_feedback": expressed_feedback,
        "private_expressed_deltas": private_expressed_deltas,
    }


def build_artifact_review_v1(mini: Any, body: ArtifactReviewRequestBaseV1) -> ArtifactReviewV1:
    unavailable_reason = review_prediction_insufficiency_reason(mini)
    if unavailable_reason:
        return build_unavailable_artifact_review_v1(mini, body, reason=unavailable_reason)
    return ArtifactReviewV1(
        **_build_artifact_review_fields(mini, body),
        mode="local_smoke",
    )


def build_unavailable_artifact_review_v1(
    mini: Any,
    body: ArtifactReviewRequestBaseV1,
    *,
    reason: str,
) -> ArtifactReviewV1:
    relationship_context = _resolve_relationship_context(body)
    return ArtifactReviewV1(
        prediction_available=False,
        mode="gated",
        unavailable_reason=reason,
        reviewer_username=getattr(mini, "username", "unknown"),
        repo_name=body.repo_name,
        artifact_summary=ArtifactSummaryV1(
            artifact_type=body.artifact_type,
            title=body.title,
        ),
        relationship_context=relationship_context,
        private_assessment=ReviewPredictionPrivateAssessmentV1(
            blocking_issues=[],
            non_blocking_issues=[],
            open_questions=[],
            positive_signals=[],
            confidence=0.0,
        ),
        delivery_policy=ReviewPredictionDeliveryPolicyV1(
            author_model=body.author_model,
            context=_resolve_delivery_context(body)[0],
            relationship_context=relationship_context,
            strictness="low",
            teaching_mode=False,
            shield_author_from_noise=True,
            say=[],
            suppress=[],
            defer=["blocking", "non_blocking", "questions", "positive"],
            risk_threshold=1.0,
            rationale=reason,
        ),
        expressed_feedback=ReviewPredictionExpressedFeedbackV1(
            summary=f"Review prediction unavailable: {reason}",
            comments=[],
            approval_state="uncertain",
        ),
    )


def build_review_prediction_v1(
    mini: Any,
    body: ReviewPredictionRequestV1,
    *,
    same_repo_precedent: dict[str, Any] | None = None,
) -> ReviewPredictionV1:
    unavailable_reason = review_prediction_insufficiency_reason(
        mini,
        same_repo_precedent=same_repo_precedent,
    )
    if unavailable_reason:
        return build_unavailable_review_prediction_v1(mini, body, reason=unavailable_reason)
    return ReviewPredictionV1(
        **_build_artifact_review_fields(
            mini,
            body,
            same_repo_precedent=same_repo_precedent,
        ),
        mode="local_smoke",
    )


def build_unavailable_review_prediction_v1(
    mini: Any,
    body: ReviewPredictionRequestV1,
    *,
    reason: str,
) -> ReviewPredictionV1:
    return ReviewPredictionV1.model_validate(
        build_unavailable_artifact_review_v1(mini, body, reason=reason).model_dump()
        | {"version": "review_prediction_v1"}
    )


def _patch_advisor_signal_framework(
    signal: ReviewPredictionSignalV1,
    framework_signals: list[ReviewPredictionFrameworkSignalV1],
) -> ReviewPredictionFrameworkSignalV1 | None:
    if not framework_signals:
        return None
    if signal.framework_id:
        for framework_signal in framework_signals:
            if framework_signal.framework_id == signal.framework_id:
                return framework_signal
    return framework_signals[0]


def _patch_advisor_guidance(
    *,
    key: str,
    summary: str,
    rationale: str,
    confidence: float,
    framework_signal: ReviewPredictionFrameworkSignalV1 | None,
    evidence: list[ReviewPredictionEvidenceV1] | None = None,
) -> PatchAdvisorGuidanceV1:
    evidence_ids: list[str] = []
    provenance_ids: list[str] = []
    framework_id: str | None = None
    revision: int | None = None
    if framework_signal:
        framework_id = framework_signal.framework_id
        revision = framework_signal.revision
        evidence_ids = framework_signal.evidence_ids
        provenance_ids = framework_signal.provenance_ids
        rationale = _append_sentence(
            rationale,
            f"Framework {framework_signal.framework_id}: {framework_signal.reason}",
        )

    return PatchAdvisorGuidanceV1(
        key=key,
        summary=summary,
        rationale=rationale,
        confidence=_coerce_confidence(confidence),
        framework_id=framework_id,
        revision=revision,
        evidence=evidence or [],
        evidence_ids=evidence_ids,
        provenance_ids=provenance_ids,
    )


def _patch_advisor_change_plan(
    review_prediction: ReviewPredictionV1,
) -> list[PatchAdvisorGuidanceV1]:
    framework_signals = review_prediction.framework_signals
    assessment = review_prediction.private_assessment
    guidance: list[PatchAdvisorGuidanceV1] = []

    for signal in assessment.blocking_issues:
        framework_signal = _patch_advisor_signal_framework(signal, framework_signals)
        guidance.append(
            _patch_advisor_guidance(
                key=f"change-{signal.key}",
                summary=f"Change the patch to address: {signal.summary}",
                rationale=signal.rationale,
                confidence=signal.confidence,
                framework_signal=framework_signal,
                evidence=signal.evidence,
            )
        )

    for signal in assessment.open_questions:
        framework_signal = _patch_advisor_signal_framework(signal, framework_signals)
        guidance.append(
            _patch_advisor_guidance(
                key=f"answer-{signal.key}",
                summary=f"Make the patch or PR description answer: {signal.summary}",
                rationale=signal.rationale,
                confidence=signal.confidence,
                framework_signal=framework_signal,
                evidence=signal.evidence,
            )
        )

    for signal in assessment.positive_signals:
        framework_signal = _patch_advisor_signal_framework(signal, framework_signals)
        guidance.append(
            _patch_advisor_guidance(
                key=f"preserve-{signal.key}",
                summary=f"Preserve this strength while editing: {signal.summary}",
                rationale=signal.rationale,
                confidence=signal.confidence,
                framework_signal=framework_signal,
                evidence=signal.evidence,
            )
        )

    return guidance[:8]


def _patch_advisor_do_not_change(
    body: PatchAdvisorRequestV1,
    framework_signals: list[ReviewPredictionFrameworkSignalV1],
    raw_frameworks: list[dict[str, Any]],
) -> list[PatchAdvisorGuidanceV1]:
    framework_by_id = {
        str(raw.get("framework_id")): raw
        for raw in raw_frameworks
        if raw.get("framework_id")
    }
    guidance: list[PatchAdvisorGuidanceV1] = []
    files = ", ".join(body.changed_files[:3])
    for framework_signal in framework_signals[:3]:
        raw = framework_by_id.get(framework_signal.framework_id, {})
        exceptions = _string_list(raw.get("exceptions")) or _string_list(raw.get("counterexamples"))
        if exceptions:
            summary = f"Do not apply {framework_signal.framework_id} outside its exceptions: {exceptions[0]}"
        elif files:
            summary = (
                f"Do not broaden the patch beyond {files} unless needed to satisfy "
                f"{framework_signal.framework_id}."
            )
        else:
            summary = f"Do not ignore the review rule captured by {framework_signal.framework_id}."

        guidance.append(
            _patch_advisor_guidance(
                key=f"do-not-{framework_signal.framework_id}",
                summary=summary,
                rationale=framework_signal.summary,
                confidence=framework_signal.confidence,
                framework_signal=framework_signal,
            )
        )
    return guidance


def _patch_advisor_risks(
    review_prediction: ReviewPredictionV1,
) -> list[PatchAdvisorGuidanceV1]:
    risks: list[PatchAdvisorGuidanceV1] = []
    framework_signals = review_prediction.framework_signals
    for signal in [
        *review_prediction.private_assessment.blocking_issues,
        *review_prediction.private_assessment.open_questions,
    ]:
        framework_signal = _patch_advisor_signal_framework(signal, framework_signals)
        risks.append(
            _patch_advisor_guidance(
                key=f"risk-{signal.key}",
                summary=signal.summary,
                rationale=signal.rationale,
                confidence=signal.confidence,
                framework_signal=framework_signal,
                evidence=signal.evidence,
            )
        )
    return risks[:6]


def _patch_advisor_objections(
    review_prediction: ReviewPredictionV1,
) -> list[PatchAdvisorGuidanceV1]:
    objections: list[PatchAdvisorGuidanceV1] = []
    framework_signals = review_prediction.framework_signals
    signal_by_key: dict[str, ReviewPredictionSignalV1] = {}
    for signal in [
        *review_prediction.private_assessment.blocking_issues,
        *review_prediction.private_assessment.non_blocking_issues,
        *review_prediction.private_assessment.open_questions,
    ]:
        signal_by_key[signal.key] = signal

    for comment in review_prediction.expressed_feedback.comments:
        key = comment.issue_key or comment.summary[:40]
        signal = signal_by_key.get(key)
        framework_signal = (
            _patch_advisor_signal_framework(signal, framework_signals)
            if signal
            else (framework_signals[0] if framework_signals else None)
        )
        objections.append(
            _patch_advisor_guidance(
                key=f"objection-{key}",
                summary=comment.summary,
                rationale=comment.rationale,
                confidence=signal.confidence if signal else 0.6,
                framework_signal=framework_signal,
                evidence=signal.evidence if signal else [],
            )
        )

    if objections:
        return objections[:6]

    for signal in review_prediction.private_assessment.blocking_issues[:3]:
        framework_signal = _patch_advisor_signal_framework(signal, framework_signals)
        objections.append(
            _patch_advisor_guidance(
                key=f"objection-{signal.key}",
                summary=signal.summary,
                rationale=signal.rationale,
                confidence=signal.confidence,
                framework_signal=framework_signal,
                evidence=signal.evidence,
            )
        )
    return objections


def _patch_advisor_evidence_references(
    framework_signals: list[ReviewPredictionFrameworkSignalV1],
) -> list[PatchAdvisorEvidenceReferenceV1]:
    return [
        PatchAdvisorEvidenceReferenceV1(
            framework_id=signal.framework_id,
            summary=signal.summary,
            reason=signal.reason,
            confidence=signal.confidence,
            revision=signal.revision,
            evidence_ids=signal.evidence_ids,
            provenance_ids=signal.provenance_ids,
            evidence_provenance=signal.evidence_provenance,
        )
        for signal in framework_signals
    ]


def build_unavailable_patch_advisor_v1(
    mini: Any,
    body: PatchAdvisorRequestV1,
    *,
    reason: str,
) -> PatchAdvisorV1:
    return PatchAdvisorV1(
        advice_available=False,
        mode="gated",
        unavailable_reason=reason,
        reviewer_username=getattr(mini, "username", "unknown"),
        repo_name=body.repo_name,
        artifact_summary=ArtifactSummaryV1(
            artifact_type=body.artifact_type,
            title=body.title,
        ),
        framework_signals=[],
        change_plan=[],
        do_not_change=[],
        risks=[],
        expected_reviewer_objections=[],
        evidence_references=[],
        review_prediction=None,
    )


def build_patch_advisor_v1(
    mini: Any,
    body: PatchAdvisorRequestV1,
    *,
    same_repo_precedent: dict[str, Any] | None = None,
) -> PatchAdvisorV1:
    raw_frameworks = _extract_decision_frameworks(getattr(mini, "principles_json", None))
    if not raw_frameworks:
        return build_unavailable_patch_advisor_v1(
            mini,
            body,
            reason="No decision-framework evidence is available for this mini.",
        )

    review_body = ReviewPredictionRequestV1.model_validate(body.model_dump())
    review_prediction = build_review_prediction_v1(
        mini,
        review_body,
        same_repo_precedent=same_repo_precedent,
    )
    if not review_prediction.framework_signals:
        return build_unavailable_patch_advisor_v1(
            mini,
            body,
            reason="Decision-framework evidence exists but no active framework signal was usable.",
        )

    return PatchAdvisorV1(
        reviewer_username=getattr(mini, "username", "unknown"),
        repo_name=body.repo_name,
        artifact_summary=ArtifactSummaryV1(
            artifact_type=body.artifact_type,
            title=body.title,
        ),
        framework_signals=review_prediction.framework_signals,
        change_plan=_patch_advisor_change_plan(review_prediction),
        do_not_change=_patch_advisor_do_not_change(
            body,
            review_prediction.framework_signals,
            raw_frameworks,
        ),
        risks=_patch_advisor_risks(review_prediction),
        expected_reviewer_objections=_patch_advisor_objections(review_prediction),
        evidence_references=_patch_advisor_evidence_references(
            review_prediction.framework_signals
        ),
        review_prediction=review_prediction,
    )


async def build_patch_advisor_v1_with_precedent(
    mini: Any,
    body: PatchAdvisorRequestV1,
    session: AsyncSession,
) -> PatchAdvisorV1:
    same_repo_precedent = await load_same_repo_precedent(
        session,
        getattr(mini, "id", None),
        body.repo_name,
    )
    return build_patch_advisor_v1(
        mini,
        body,
        same_repo_precedent=same_repo_precedent,
    )


async def build_review_prediction_v1_with_precedent(
    mini: Any,
    body: ReviewPredictionRequestV1,
    session: AsyncSession,
) -> ReviewPredictionV1:
    same_repo_precedent = await load_same_repo_precedent(
        session,
        getattr(mini, "id", None),
        body.repo_name,
    )
    return build_review_prediction_v1(
        mini,
        body,
        same_repo_precedent=same_repo_precedent,
    )
