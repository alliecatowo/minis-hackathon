from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.models.schemas import (
    BehavioralContext,
    MotivationsProfile,
    ReviewArtifactSummaryV1,
    ReviewPredictionCommentV1,
    ReviewPredictionDeliveryPolicyV1,
    ReviewPredictionEvidenceV1,
    ReviewPredictionExpressedFeedbackV1,
    ReviewPredictionPrivateAssessmentV1,
    ReviewPredictionRequestV1,
    ReviewPredictionSignalV1,
    ReviewPredictionV1,
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


def _build_request_text(body: ReviewPredictionRequestV1) -> str:
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


def _artifact_kind_label(body: ReviewPredictionRequestV1) -> str:
    return body.artifact_type.replace("_", " ")


def _artifact_scope_label(body: ReviewPredictionRequestV1) -> str:
    if body.artifact_type == "pull_request":
        return "change"
    return "artifact"


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


def _resolve_delivery_context(body: ReviewPredictionRequestV1) -> tuple[str, str | None]:
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


def _build_evidence_pool(mini: Any, body: ReviewPredictionRequestV1) -> list[ReviewPredictionEvidenceV1]:
    request_text = _build_request_text(body)
    behavioral_context = _parse_behavioral_context(getattr(mini, "behavioral_context_json", None))
    motivations = _parse_motivations(getattr(mini, "motivations_json", None))

    evidence: list[ReviewPredictionEvidenceV1] = []

    for entry in _review_entries(behavioral_context)[:2]:
        evidence.append(
            ReviewPredictionEvidenceV1(
                source="behavioral_context",
                detail=f'{entry["context"]}: {entry["detail"][:240]}',
            )
        )

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


def _blended_evidence_score(
    item: ReviewPredictionEvidenceV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
) -> tuple[float, int]:
    lower_detail = item.detail.lower()
    lexical = sum(1 for keyword in keywords if keyword in lower_detail)
    recency = _infer_recency_score(item.detail)
    principle_frequency, cross_context_consistency, source_confidence = _stability_components(
        item,
        evidence_pool,
        keywords,
    )
    stability = (
        (principle_frequency * 0.35)
        + (cross_context_consistency * 0.30)
        + (source_confidence * 0.35)
    )

    # Explicitly favor stable long-horizon framework signals over recency spikes.
    blend = (recency * 0.25) + (stability * 0.75)
    # Keep lexical relevance as a secondary ordering signal.
    return blend, lexical


def _pick_evidence(
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
    max_items: int = 2,
) -> list[ReviewPredictionEvidenceV1]:
    if not evidence_pool:
        return []

    ranked: list[tuple[float, int, ReviewPredictionEvidenceV1]] = []
    for item in evidence_pool:
        blended, lexical = _blended_evidence_score(item, evidence_pool, keywords)
        ranked.append((blended, lexical, item))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = [item for _blend, score, item in ranked if score > 0][:max_items]
    if selected:
        return selected
    return [item for _blend, _score, item in ranked[:max_items]]


def _contains_any(text: str, keywords: set[str]) -> bool:
    lower_text = text.lower()
    return any(keyword in lower_text for keyword in keywords)


def _has_matching_file(paths: list[str], patterns: tuple[str, ...]) -> bool:
    lowered = [path.lower() for path in paths]
    return any(pattern in path for path in lowered for pattern in patterns)


def _derive_delivery_policy(
    mini: Any,
    body: ReviewPredictionRequestV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
) -> ReviewPredictionDeliveryPolicyV1:
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
    if body.author_model == "senior_peer":
        score += 1
        rationale_parts.append("more willing to be direct with senior peers")
    elif body.author_model == "junior_peer":
        score -= 1
        rationale_parts.append("junior-peer relationship shifts toward coaching")
    elif body.author_model == "trusted_peer" and (has_noise_shield_signal or pragmatism >= 7.0):
        score -= 1
        rationale_parts.append("trusted-peer relationship narrows feedback to high-signal issues")

    strictness = "medium"
    if score <= 0:
        strictness = "low"
    elif score >= 3:
        strictness = "high"

    if strictness == "high" and body.author_model == "junior_peer":
        strictness = "medium"
        rationale_parts.append("junior-peer delivery keeps strictness below maximum")
    if strictness == "high" and resolved_context == "exploratory":
        strictness = "medium"
        rationale_parts.append("exploratory context avoids production-grade strictness")

    teaching_mode = body.author_model == "junior_peer" or (
        resolved_context not in {"hotfix", "incident"}
        and (has_teaching_signal or resolved_context == "exploratory")
    )
    shield_author_from_noise = resolved_context in {"hotfix", "incident", "exploratory"} or (
        body.author_model in {"trusted_peer", "junior_peer"} and strictness != "high"
    )
    if has_noise_shield_signal:
        shield_author_from_noise = True
        rationale_parts.append("stored review context shows low tolerance for noisy churn")

    if not rationale_parts and evidence_pool:
        rationale_parts.append("using stored review-context evidence")
    if not rationale_parts:
        rationale_parts.append("falling back to neutral review policy defaults")

    return ReviewPredictionDeliveryPolicyV1(
        author_model=body.author_model,
        context=resolved_context,
        strictness=strictness,
        teaching_mode=teaching_mode,
        shield_author_from_noise=shield_author_from_noise,
        rationale=", ".join(rationale_parts),
    )


def _make_signal(
    key: str,
    summary: str,
    rationale: str,
    confidence: float,
    evidence_pool: list[ReviewPredictionEvidenceV1],
    keywords: set[str],
) -> ReviewPredictionSignalV1:
    return ReviewPredictionSignalV1(
        key=key,
        summary=summary,
        rationale=rationale,
        confidence=confidence,
        evidence=_pick_evidence(evidence_pool, keywords),
    )


def _build_private_assessment(
    mini: Any,
    body: ReviewPredictionRequestV1,
    policy: ReviewPredictionDeliveryPolicyV1,
    evidence_pool: list[ReviewPredictionEvidenceV1],
) -> ReviewPredictionPrivateAssessmentV1:
    request_text = _build_request_text(body)
    request_text_lower = request_text.lower()
    delivery_context = policy.context
    artifact_scope = _artifact_scope_label(body)
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
                summary="Likely to scrutinize auth and permission boundaries before signing off.",
                rationale="Changes touching credentials or authorization usually read as high-severity review territory.",
                confidence=0.82,
                evidence_pool=evidence_pool,
                keywords={"auth", "permission", "security", "token"},
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
                )
            )
        else:
            positive_signals.append(
                _make_signal(
                    key="migration-awareness",
                    summary=f"The {artifact_scope} already signals migration or compatibility awareness.",
                    rationale="Explicit migration notes reduce ambiguity on risky data-shape changes.",
                    confidence=0.71,
                    evidence_pool=evidence_pool,
                    keywords={"migration", "schema", "database"},
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
            )
        )

    if risk_keywords_present and not has_tests:
        target = blocking_issues if policy.strictness == "high" or code_quality >= 7.0 else open_questions
        target.append(
            _make_signal(
                key="test-coverage",
                summary="Would likely ask for stronger test coverage around the risky path.",
                rationale="Risky behavior changes without explicit tests are a recurring review trigger for quality-focused reviewers.",
                confidence=0.78 if target is blocking_issues else 0.68,
                evidence_pool=evidence_pool,
                keywords={"test", "coverage", "review", "quality"},
            )
        )
    elif has_tests:
        positive_signals.append(
            _make_signal(
                key="tests-present",
                summary=f"The {artifact_scope} already mentions tests or coverage work.",
                rationale="Explicit test coverage lowers the probability of a hard block.",
                confidence=0.72,
                evidence_pool=evidence_pool,
                keywords={"test", "coverage"},
            )
        )

    if risk_keywords_present and not has_rollout and delivery_context != "exploratory":
        open_questions.append(
            _make_signal(
                key="rollout-safety",
                summary="Would likely ask about rollout safety, monitoring, or rollback posture.",
                rationale="Risky changes are easier to ship when the blast radius and recovery path are explicit.",
                confidence=0.66,
                evidence_pool=evidence_pool,
                keywords={"rollback", "metrics", "logging", "flag", "monitor"},
            )
        )
    elif has_rollout:
        positive_signals.append(
            _make_signal(
                key="rollout-awareness",
                summary=f"The {artifact_scope} already mentions rollout or observability guardrails.",
                rationale="Feature flags, logging, or rollback notes usually read as good review hygiene.",
                confidence=0.67,
                evidence_pool=evidence_pool,
                keywords={"rollback", "metrics", "logging", "flag", "monitor"},
            )
        )

    if _contains_any(request_text_lower, {"refactor", "rename", "cleanup", "naming", "readability"}):
        non_blocking_issues.append(
            _make_signal(
                key="clarity-pass",
                summary="Could leave a non-blocking note on naming or boundary clarity.",
                rationale="Refactors and cleanup work often trigger clarity comments even when the core idea is sound.",
                confidence=0.58,
                evidence_pool=evidence_pool,
                keywords={"clarity", "naming", "readability", "refactor"},
            )
        )

    if has_docs:
        positive_signals.append(
            _make_signal(
                key="docs-present",
                summary=f"Documentation or inline explanation is already part of the {artifact_scope}.",
                rationale="Clear written context usually improves review throughput and reduces back-and-forth.",
                confidence=0.61,
                evidence_pool=evidence_pool,
                keywords={"docs", "documentation", "readme", "comment"},
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
    body: ReviewPredictionRequestV1,
) -> str:
    artifact_scope = _artifact_scope_label(body)
    if approval_state == "request_changes":
        if policy.strictness == "high":
            summary = "Would likely request changes directly and center the review on the main sign-off risks."
        elif policy.strictness == "low":
            summary = "Would likely ask for a narrow set of changes before sign-off."
        else:
            summary = "Would likely ask for changes, but keep the feedback focused on the main risks."
    elif approval_state == "comment":
        if policy.shield_author_from_noise:
            summary = f"Would likely leave a narrow set of high-signal comments without blocking the {artifact_scope}."
        else:
            summary = f"Would likely leave a small set of comments or questions without blocking the {artifact_scope}."
    elif approval_state == "approve":
        if policy.shield_author_from_noise:
            summary = "Would likely approve without piling on extra nits."
        else:
            summary = "Would likely approve and mention the strongest positive signals."
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
        elif policy.strictness == "high" or policy.author_model == "senior_peer":
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
        if policy.strictness == "high" or policy.author_model == "senior_peer":
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
        summary=signal.summary,
        rationale=_append_sentence(signal.rationale, _comment_delivery_addendum(signal_type, policy)),
    )


def _build_expressed_feedback(
    assessment: ReviewPredictionPrivateAssessmentV1,
    policy: ReviewPredictionDeliveryPolicyV1,
    body: ReviewPredictionRequestV1,
) -> ReviewPredictionExpressedFeedbackV1:
    comments: list[ReviewPredictionCommentV1] = []

    if assessment.blocking_issues:
        approval_state = "request_changes"
        summary = _feedback_summary(approval_state, policy, body)

        surfaced_blockers = assessment.blocking_issues[: _comment_limit(policy, "blocking")]
        surfaced_non_blocking = assessment.non_blocking_issues[: _comment_limit(policy, "non_blocking")]
        surfaced_questions = assessment.open_questions[: _comment_limit(policy, "questions")]

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
    elif assessment.non_blocking_issues or assessment.open_questions:
        approval_state = "comment"
        summary = _feedback_summary(approval_state, policy, body)
        for signal in assessment.open_questions[: _comment_limit(policy, "questions")]:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="question",
                    disposition="comment",
                    policy=policy,
                )
            )
        for signal in assessment.non_blocking_issues[: _comment_limit(policy, "non_blocking")]:
            comments.append(
                _make_expressed_comment(
                    signal=signal,
                    signal_type="note",
                    disposition="comment",
                    policy=policy,
                )
            )
    elif assessment.positive_signals:
        approval_state = "approve"
        summary = _feedback_summary(approval_state, policy, body)
        for signal in assessment.positive_signals[: _comment_limit(policy, "positive")]:
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


def build_review_prediction_v1(mini: Any, body: ReviewPredictionRequestV1) -> ReviewPredictionV1:
    evidence_pool = _build_evidence_pool(mini, body)
    policy = _derive_delivery_policy(mini, body, evidence_pool)
    assessment = _build_private_assessment(mini, body, policy, evidence_pool)
    expressed_feedback = _build_expressed_feedback(assessment, policy, body)

    return ReviewPredictionV1(
        reviewer_username=getattr(mini, "username", "unknown"),
        repo_name=body.repo_name,
        artifact_summary=ReviewArtifactSummaryV1(
            artifact_type=body.artifact_type,
            title=body.title,
        ),
        private_assessment=assessment,
        delivery_policy=policy,
        expressed_feedback=expressed_feedback,
    )
