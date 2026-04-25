"""Eval runner — orchestrates sending turns to a mini and scoring responses.

For each (subject, golden turn): POST to /api/minis/{mini_id}/chat,
collect the streamed response, score via judge, and aggregate into an EvalReport.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from eval.judge import ScoreCard, SubjectSummary, TurnScore, compute_framework_summary, score_response
from eval.review import HeldOutReviewExpectation, compute_review_agreement

logger = logging.getLogger(__name__)

_SCORECARD_NOT_AVAILABLE = "scorecard_unavailable"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SubjectConfig:
    """Loaded subject YAML."""

    username: str
    display_name: str
    why_selected: str
    expected_voice_markers: list[str]

    @classmethod
    def from_yaml(cls, path: Path) -> "SubjectConfig":
        data = yaml.safe_load(path.read_text())
        return cls(
            username=data["username"],
            display_name=data["display_name"],
            why_selected=data.get("why_selected", ""),
            expected_voice_markers=data.get("expected_voice_markers", []),
        )


@dataclass
class GoldenTurn:
    """A single golden turn from the turns YAML."""

    id: str
    prompt: str
    reference_answer: str
    rubric: list[dict[str, Any]]
    case_type: str = "baseline"
    held_out_review: HeldOutReviewExpectation | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GoldenTurn":
        return cls(
            id=data["id"],
            prompt=data["prompt"],
            reference_answer=data["reference_answer"],
            rubric=data.get("rubric", []),
            case_type=data.get("case_type", "baseline"),
            held_out_review=(
                HeldOutReviewExpectation.from_dict(data["held_out_review"])
                if data.get("held_out_review")
                else None
            ),
        )


@dataclass
class GoldenTurnFile:
    """Loaded golden turns YAML for one subject."""

    subject: str
    turns: list[GoldenTurn]

    @classmethod
    def from_yaml(cls, path: Path) -> "GoldenTurnFile":
        data = yaml.safe_load(path.read_text())
        return cls(
            subject=data["subject"],
            turns=[GoldenTurn.from_dict(t) for t in data.get("turns", [])],
        )


@dataclass
class EvalReport:
    """Complete evaluation results for all subjects."""

    summaries: list[SubjectSummary] = field(default_factory=list)
    base_url: str = ""
    model_used: str = ""

    def all_turn_scores(self) -> list[TurnScore]:
        return [ts for s in self.summaries for ts in s.turn_scores]

    def overall_avg(self) -> float:
        scores = [
            ts.scorecard.overall_score
            for s in self.summaries
            for ts in s.turn_scores
            if not ts.failed
        ]
        if not scores:
            return 0.0
        return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _send_chat_turn(
    client: httpx.AsyncClient,
    base_url: str,
    mini_id: str,
    prompt: str,
    token: str | None = None,
) -> str:
    """POST to /api/minis/{mini_id}/chat and collect the full response text.

    Handles SSE streaming (text/event-stream) by accumulating 'chunk' events,
    and also handles plain JSON responses (for tests / simple endpoints).
    """
    headers: dict[str, str] = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/api/minis/{mini_id}/chat"
    payload = {"message": prompt}

    collected_text: list[str] = []

    async with client.stream("POST", url, json=payload, headers=headers, timeout=120.0) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")

        if "event-stream" in content_type:
            # Collect SSE chunk events
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    event_type = event.get("type", "")
                    if event_type == "chunk":
                        collected_text.append(event.get("data", ""))
                    elif event_type == "done":
                        break
        else:
            # Plain JSON — used in some test scenarios
            body = await resp.aread()
            try:
                data = json.loads(body)
                if isinstance(data, dict):
                    collected_text.append(data.get("response", data.get("message", str(data))))
                else:
                    collected_text.append(str(data))
            except json.JSONDecodeError:
                collected_text.append(body.decode())

    return "".join(collected_text).strip()


async def _resolve_mini_id(client: httpx.AsyncClient, base_url: str, username: str) -> str:
    """Resolve a username to a mini ID."""
    url = f"{base_url}/api/minis/by-username/{username}"
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data["id"]


# ---------------------------------------------------------------------------
# Agreement scorecard fetch
# ---------------------------------------------------------------------------


async def _fetch_agreement_scorecard(
    client: httpx.AsyncClient,
    base_url: str,
    username: str,
    token: str | None = None,
) -> dict | None:
    """Fetch the agreement scorecard summary for a mini by username.

    First resolves the mini's UUID via GET /api/minis/by-username/{username},
    then calls GET /api/minis/{id}/agreement-scorecard-summary.

    Returns the scorecard dict on success, or None if the mini is not found,
    has insufficient data, or the request fails for any reason.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Step 1: resolve mini ID from username
    try:
        resp = await client.get(
            f"{base_url}/api/minis/by-username/{username}",
            headers=headers,
            timeout=30.0,
        )
        if resp.status_code == 404:
            logger.debug("Mini not found for username %r — skipping scorecard fetch", username)
            return None
        resp.raise_for_status()
        mini_data = resp.json()
        mini_id = mini_data.get("id")
        if not mini_id:
            logger.warning("No id in mini response for %r", username)
            return None
    except Exception as exc:
        logger.warning("Failed to resolve mini ID for %r: %s", username, exc)
        return None

    # Step 2: fetch the agreement scorecard summary
    try:
        resp = await client.get(
            f"{base_url}/api/minis/{mini_id}/agreement-scorecard-summary",
            headers=headers,
            timeout=30.0,
        )
        if resp.status_code in (401, 403, 404):
            logger.debug(
                "Agreement scorecard not accessible for mini %r (status %d)",
                mini_id,
                resp.status_code,
            )
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Failed to fetch agreement scorecard for mini %r: %s", mini_id, exc)
        return None


# ---------------------------------------------------------------------------
# Decision-framework fetch
# ---------------------------------------------------------------------------


async def _fetch_decision_frameworks(
    client: httpx.AsyncClient,
    base_url: str,
    username: str,
    token: str | None = None,
) -> dict | None:
    """Fetch the decision-framework profile summary for a mini by username.

    Calls GET /api/minis/by-username/{username}/decision-frameworks?limit=50,
    computes summary metrics via ``compute_framework_summary``, and returns the
    summary dict.

    Returns ``None`` when:
    - the mini is not found (404)
    - the endpoint is unavailable or returns a non-success status
    - any network / parse error occurs
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = await client.get(
            f"{base_url}/api/minis/by-username/{username}/decision-frameworks",
            params={"limit": 50},
            headers=headers,
            timeout=30.0,
        )
        if resp.status_code == 404:
            logger.debug(
                "Decision frameworks not found for username %r — skipping", username
            )
            return None
        if resp.status_code in (401, 403):
            logger.debug(
                "Decision frameworks not accessible for %r (status %d)", username, resp.status_code
            )
            return None
        resp.raise_for_status()
        data = resp.json()
        # The endpoint may return a list directly or a wrapper dict with a
        # "frameworks" / "items" key — handle both shapes gracefully.
        if isinstance(data, list):
            frameworks = data
        elif isinstance(data, dict):
            frameworks = data.get("frameworks") or data.get("items") or []
        else:
            frameworks = []
        return compute_framework_summary(frameworks)
    except Exception as exc:
        logger.warning("Failed to fetch decision frameworks for %r: %s", username, exc)
        return None


# ---------------------------------------------------------------------------
# Main eval runner
# ---------------------------------------------------------------------------


async def run_eval(
    subject_files: list[Path],
    turn_files: list[Path],
    base_url: str,
    token: str | None = None,
    judge_model: str | None = None,
) -> EvalReport:
    """Run the full fidelity evaluation.

    For each subject + turn file pair, sends each golden turn prompt to the mini
    chat endpoint, scores the response via the judge, and aggregates results.

    Args:
        subject_files: Paths to subject YAML files (one per subject).
        turn_files: Paths to golden turns YAML files (one per subject).
        base_url: Base URL of the Minis backend (e.g. http://localhost:8000).
        token: Optional Bearer token for auth.
        judge_model: Optional model override for the judge; defaults to STANDARD tier.

    Returns:
        EvalReport with all subject summaries and turn scores.
    """
    # Build username -> subject config map
    subjects: dict[str, SubjectConfig] = {}
    for sf in subject_files:
        cfg = SubjectConfig.from_yaml(sf)
        subjects[cfg.username] = cfg

    # Build username -> turns map
    turns_by_subject: dict[str, GoldenTurnFile] = {}
    for tf in turn_files:
        gtf = GoldenTurnFile.from_yaml(tf)
        turns_by_subject[gtf.subject] = gtf

    report = EvalReport(base_url=base_url, model_used=judge_model or "")

    async with httpx.AsyncClient(timeout=120.0) as client:
        for username, subject in subjects.items():
            if username not in turns_by_subject:
                logger.warning("No golden turns found for subject %r — skipping", username)
                continue

            gtf = turns_by_subject[username]
            summary = SubjectSummary(subject=username)

            # 0. Resolve mini ID once per subject.
            try:
                mini_id = await _resolve_mini_id(client, base_url, username)
            except Exception as exc:
                logger.error("Failed to resolve mini ID for %s: %s", username, exc)
                continue

            for turn in gtf.turns:
                logger.info("Evaluating %s / %s ...", username, turn.id)

                # 1. Get mini response
                try:
                    mini_response = await _send_chat_turn(
                        client=client,
                        base_url=base_url,
                        mini_id=mini_id,
                        prompt=turn.prompt,
                        token=token,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to get mini response for %s/%s: %s",
                        username,
                        turn.id,
                        exc,
                    )
                    summary.turn_scores.append(
                        TurnScore(
                            subject=username,
                            turn_id=turn.id,
                            prompt=turn.prompt,
                            reference_answer=turn.reference_answer,
                            mini_response="",
                            scorecard=ScoreCard(
                                overall_score=1,
                                voice_match=1,
                                factual_accuracy=1,
                                framework_consistency=1,
                                recency_bias_penalty=1.0,
                                overall_rationale="Mini chat request failed.",
                            ),
                            case_type=turn.case_type,
                            error=str(exc),
                        )
                    )
                    continue

                # 2. Score via judge
                try:
                    scorecard = await score_response(
                        reference_answer=turn.reference_answer,
                        rubric=turn.rubric,
                        mini_response=mini_response,
                        turn_id=turn.id,
                        model=judge_model,
                        held_out_review=turn.held_out_review,
                    )
                except Exception as exc:
                    logger.error(
                        "Judge scoring failed for %s/%s: %s",
                        username,
                        turn.id,
                        exc,
                    )
                    summary.turn_scores.append(
                        TurnScore(
                            subject=username,
                            turn_id=turn.id,
                            prompt=turn.prompt,
                            reference_answer=turn.reference_answer,
                            mini_response=mini_response,
                            scorecard=ScoreCard(
                                overall_score=1,
                                voice_match=1,
                                factual_accuracy=1,
                                framework_consistency=1,
                                recency_bias_penalty=1.0,
                                overall_rationale="Judge scoring failed.",
                            ),
                            case_type=turn.case_type,
                            error=str(exc),
                        )
                    )
                    continue

                summary.turn_scores.append(
                    TurnScore(
                        subject=username,
                        turn_id=turn.id,
                        prompt=turn.prompt,
                        reference_answer=turn.reference_answer,
                        mini_response=mini_response,
                        scorecard=scorecard,
                        case_type=turn.case_type,
                        review_agreement=(
                            compute_review_agreement(
                                turn.held_out_review, scorecard.review_selection
                            )
                            if turn.held_out_review
                            else None
                        ),
                    )
                )

            # Fetch agreement scorecard for this subject
            logger.info("Fetching agreement scorecard for %s ...", username)
            scorecard_data = await _fetch_agreement_scorecard(
                client=client,
                base_url=base_url,
                username=username,
                token=token,
            )
            summary.agreement_scorecard = scorecard_data

            # Fetch decision-framework profile for this subject
            logger.info("Fetching decision frameworks for %s ...", username)
            summary.decision_frameworks_summary = await _fetch_decision_frameworks(
                client=client,
                base_url=base_url,
                username=username,
                token=token,
            )

            report.summaries.append(summary)

    return report
