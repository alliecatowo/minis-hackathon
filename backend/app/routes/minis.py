import asyncio
import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agreement_scorecard import build_agreement_scorecard_summary
from app.core.access import require_mini_access, require_mini_owner
from app.core.auth import get_current_user, get_optional_user, require_trusted_service
from app.core.config import settings
from app.core.feature_flags import FLAGS
from app.core.rate_limit import check_rate_limit
from app.core.review_prediction import (
    build_artifact_review_v1,
    build_review_prediction_v1_with_precedent,
)
from app.core.review_predictor_agent import predict_artifact_review, predict_review
from app.db import async_session, get_session
from app.models.evidence import ReviewCycle
from app.models.mini import Mini
from app.models.schemas import (
    AgreementScorecardSummary,
    ArtifactReviewCycleOutcomeUpdateRequest,
    ArtifactReviewCyclePredictionUpsertRequest,
    ArtifactReviewCycleRecord,
    ArtifactReviewRequestV1,
    ArtifactReviewV1,
    AtRiskFramework,
    CreateMiniRequest,
    MiniDetail,
    MiniPublic,
    RetireFrameworkResponse,
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
    ReviewCycleRecord,
    MiniSummary,
    MiniTrustedService,
    ReviewPredictionRequestV1,
    ReviewPredictionV1,
)
from app.models.user import User
from app.plugins.registry import registry
from app.artifact_review_cycles import (
    finalize_artifact_review_outcome,
    upsert_artifact_review_prediction,
)
from app.review_cycles import finalize_review_cycle, upsert_review_cycle_prediction
from app.synthesis.pipeline import (
    cleanup_event_queue,
    get_event_queue,
    run_pipeline_with_events,
)

# ── Dataset endpoint in-memory rate limiter ───────────────────────────────────
# Keyed by mini_id → last generation timestamp (UTC)
_dataset_rate_limit: dict[str, datetime.datetime] = {}
_DATASET_RATE_LIMIT_SECONDS = 600  # 10 minutes

router = APIRouter(prefix="/minis", tags=["minis"])


async def _build_artifact_review_response(
    mini: Mini,
    body: ArtifactReviewRequestV1,
    session: AsyncSession,
) -> ArtifactReviewV1:
    if FLAGS["REVIEW_PREDICTOR_LLM_ENABLED"].is_enabled():
        return await predict_artifact_review(mini, body, session)
    return build_artifact_review_v1(mini, body)


async def _build_review_prediction_response(
    mini: Mini,
    body: ReviewPredictionRequestV1,
    session: AsyncSession,
) -> ReviewPredictionV1:
    if FLAGS["REVIEW_PREDICTOR_LLM_ENABLED"].is_enabled():
        return await predict_review(mini, body, session)
    return await build_review_prediction_v1_with_precedent(mini, body, session)


@router.get("/sources")
async def list_sources():
    """List available ingestion sources."""
    source_names = registry.list_sources()
    source_info = {
        "github": {"name": "GitHub", "description": "Commits, PRs, and reviews"},
        "claude_code": {"name": "Claude Code", "description": "Conversation history"},
        "blog": {"name": "Blog / RSS", "description": "Blog posts and articles via RSS feed"},
        "hackernews": {"name": "Hacker News", "description": "Comments, posts, and tech opinions"},
        "stackoverflow": {"name": "Stack Overflow", "description": "Top answers and expertise"},
        "devblog": {"name": "Dev.to", "description": "Dev.to articles, tutorials, and discussions"},
        "website": {"name": "Website", "description": "Personal or project website pages"},
    }
    return [
        {
            "id": s,
            "name": source_info.get(s, {}).get("name", s),
            "description": source_info.get(s, {}).get("description", ""),
            "available": True,
        }
        for s in source_names
    ]


@router.get("/promo")
async def get_promo_mini(
    session: AsyncSession = Depends(get_session),
):
    """Get the promo mini for anonymous chat. Returns 404 if not configured or not found."""
    promo_username = settings.promo_mini_username
    if not promo_username:
        raise HTTPException(status_code=404, detail="No promo mini configured")

    result = await session.execute(
        select(Mini)
        .where(
            Mini.username == promo_username.lower(),
            Mini.visibility == "public",
        )
        .order_by(Mini.created_at)
    )
    mini = result.scalars().first()
    if not mini:
        raise HTTPException(status_code=404, detail="Promo mini not found")
    return MiniSummary.model_validate(mini)


@router.post("", status_code=202)
async def create_mini(
    request: Request,
    body: CreateMiniRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create a new mini. Kicks off pipeline in background with selected sources."""
    from app.middleware.ip_rate_limit import check_mini_create_ip_limit

    ip = request.client.host if request.client else "unknown"
    check_mini_create_ip_limit(ip, user=user)

    await check_rate_limit(user.id, "mini_create", session)
    username = body.username.strip().lower()
    sources = body.sources
    owner_id = user.id

    # Check if this user already owns a mini with this username.
    result = await session.execute(
        select(Mini).where(Mini.username == username, Mini.owner_id == owner_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-run pipeline (allows regeneration and recovery from stuck state)
        existing.status = "processing"
        await session.commit()
        mini = existing
    else:
        # Check for a stale public (unowned) mini with this username that we
        # can reassign to the requesting user rather than creating a duplicate.
        result = await session.execute(
            select(Mini).where(Mini.username == username, Mini.owner_id.is_(None))
        )
        stale = result.scalars().first()

        if stale:
            # Reassign the stale row to this user and re-run the pipeline.
            stale.owner_id = owner_id
            stale.status = "processing"
            await session.commit()
            mini = stale
        else:
            # Check if another user already owns this username.
            result = await session.execute(
                select(Mini).where(Mini.username == username, Mini.owner_id.isnot(None))
            )
            taken = result.scalars().first()
            if taken:
                raise HTTPException(
                    status_code=409,
                    detail=f"A mini for '{username}' is already owned by another user",
                )

            # Create new
            mini = Mini(username=username, status="processing", owner_id=owner_id)
            session.add(mini)
            await session.commit()
            await session.refresh(mini)

    # Save repo exclusions
    if body.excluded_repos:
        from app.models.ingestion_data import MiniRepoConfig

        for repo_name in body.excluded_repos:
            config = MiniRepoConfig(
                mini_id=mini.id,
                repo_full_name=repo_name,
                included=False,
            )
            session.add(config)
        await session.flush()

    # Kick off pipeline in background
    asyncio.create_task(
        run_pipeline_with_events(
            username,
            async_session,
            sources=sources,
            owner_id=owner_id,
            mini_id=mini.id,
            source_identifiers=body.source_identifiers or None,
        )
    )

    return MiniSummary.model_validate(mini)


@router.get("")
async def list_minis(
    mine: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """List minis. Use ?mine=true to list only your own (requires auth)."""
    if mine:
        if user is None:
            raise HTTPException(
                status_code=401, detail="Authentication required to list your minis"
            )
        result = await session.execute(
            select(Mini).where(Mini.owner_id == user.id).order_by(Mini.created_at.desc())
        )
    else:
        result = await session.execute(
            select(Mini).where(Mini.visibility == "public").order_by(Mini.created_at.desc())
        )
    minis = result.scalars().all()
    return [MiniSummary.model_validate(m) for m in minis]


# NOTE: /by-username route MUST be defined before /{id} to avoid path conflicts
@router.get("/by-username/{username}")
async def get_mini_by_username(
    username: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Get a mini by username. Returns user's own if logged in, otherwise first public match."""
    username_lower = username.lower()

    # If logged in, check for user's own mini first
    if user is not None:
        result = await session.execute(
            select(Mini).where(Mini.username == username_lower, Mini.owner_id == user.id)
        )
        own_mini = result.scalar_one_or_none()
        if own_mini:
            return MiniDetail.model_validate(own_mini)

    # Fall back to public matches — prefer owned rows over stale public rows,
    # then newest first so a fresh pipeline result wins over an old one.
    # ORDER BY: owned rows (owner_id IS NOT NULL) come first, then newest.
    result = await session.execute(
        select(Mini)
        .where(Mini.username == username_lower, Mini.visibility == "public")
        .order_by(Mini.owner_id.is_(None), Mini.created_at.desc())
    )
    mini = result.scalars().first()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    return MiniPublic.model_validate(mini)


@router.get("/by-username/{username}/decision-frameworks")
async def get_decision_frameworks_by_username(
    username: str,
    limit: int = Query(default=10, ge=1, le=50),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Return the top-N decision frameworks for a mini, sorted by confidence desc.

    Public endpoint — unauthenticated access allowed for public minis.
    Returns the same shape as the MCP get_decision_frameworks tool.
    """
    username_lower = username.lower()

    # Prefer the owner's mini if authenticated
    mini: Mini | None = None
    if user is not None:
        result = await session.execute(
            select(Mini).where(Mini.username == username_lower, Mini.owner_id == user.id)
        )
        mini = result.scalar_one_or_none()

    if mini is None:
        result = await session.execute(
            select(Mini)
            .where(Mini.username == username_lower, Mini.visibility == "public")
            .order_by(Mini.owner_id.is_(None), Mini.created_at.desc())
        )
        mini = result.scalars().first()

    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    principles_json = mini.principles_json

    # Extract the frameworks list from the stored JSON blob.
    # Supports both a bare DecisionFrameworkProfile payload and the legacy
    # principles matrix shape (with a top-level "decision_frameworks" key).
    raw_frameworks: list = []
    if isinstance(principles_json, dict):
        if "frameworks" in principles_json and "version" in principles_json:
            # Already a DecisionFrameworkProfile
            raw_frameworks = principles_json.get("frameworks") or []
        elif "decision_frameworks" in principles_json:
            df = principles_json["decision_frameworks"]
            if isinstance(df, dict):
                raw_frameworks = df.get("frameworks") or []
        else:
            raw_frameworks = principles_json.get("frameworks") or []

    _BADGE_HIGH = 0.7
    _BADGE_LOW = 0.3

    def _badge(conf: float) -> str | None:
        if conf > _BADGE_HIGH:
            return "high"
        if conf < _BADGE_LOW:
            return "low"
        return None

    # Filter, sort, slice
    filtered = [
        fw
        for fw in raw_frameworks
        if (
            isinstance(fw, dict)
            and not fw.get("retired", False)
            and fw.get("confidence", 0.0) >= min_confidence
        )
    ]
    filtered.sort(key=lambda fw: (-fw.get("confidence", 0.0), -fw.get("revision", 0)))
    filtered = filtered[:limit]

    out: list[dict] = []
    for fw in filtered:
        conf: float = fw.get("confidence", 0.0)
        out.append(
            {
                "framework_id": fw.get("framework_id"),
                "confidence": conf,
                "revision": fw.get("revision", 0),
                "trigger": fw.get("condition") or fw.get("trigger"),
                "action": fw.get("block_policy") or fw.get("approval_policy") or fw.get("action"),
                "value": (
                    fw.get("value_ids", [None])[0] if fw.get("value_ids") else fw.get("value")
                ),
                "badge": _badge(conf),
            }
        )

    total = len(out)
    mean_conf = sum(fw["confidence"] for fw in out) / total if total else 0.0
    max_rev = max((fw["revision"] for fw in out), default=0)

    return {
        "username": mini.username,
        "frameworks": out,
        "summary": {
            "total": total,
            "mean_confidence": round(mean_conf, 4),
            "max_revision": max_rev,
        },
    }


@router.get("/trusted/by-username/{username}")
async def get_trusted_mini_by_username(
    username: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Get the private mini payload needed by trusted service integrations."""
    username_lower = username.lower()

    result = await session.execute(
        select(Mini)
        .where(Mini.username == username_lower)
        .order_by(Mini.owner_id.is_(None), Mini.created_at.desc())
    )
    mini = result.scalars().first()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    return MiniTrustedService.model_validate(mini)


@router.put("/trusted/{mini_id}/review-cycles")
async def put_review_cycle_prediction(
    mini_id: str,
    body: ReviewCyclePredictionUpsertRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Create or refresh the predicted state for one review cycle."""
    cycle = await upsert_review_cycle_prediction(session, mini_id, body)
    return ReviewCycleRecord.model_validate(cycle)


@router.patch("/trusted/{mini_id}/review-cycles")
async def patch_review_cycle_outcome(
    mini_id: str,
    body: ReviewCycleOutcomeUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Attach the eventual human review outcome and compact delta metrics."""
    cycle = await finalize_review_cycle(session, mini_id, body)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Review cycle not found")
    return ReviewCycleRecord.model_validate(cycle)


@router.put("/trusted/{mini_id}/artifact-review-cycles")
async def put_artifact_review_cycle_prediction(
    mini_id: str,
    body: ArtifactReviewCyclePredictionUpsertRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Create or refresh the predicted state for one artifact-review cycle (design_doc / issue_plan)."""
    cycle = await upsert_artifact_review_prediction(session, mini_id, body)
    return ArtifactReviewCycleRecord.model_validate(cycle)


@router.patch("/trusted/{mini_id}/artifact-review-cycles")
async def patch_artifact_review_cycle_outcome(
    mini_id: str,
    body: ArtifactReviewCycleOutcomeUpdateRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Persist the human artifact-review outcome and trigger Evidence writeback + framework deltas."""
    cycle = await finalize_artifact_review_outcome(session, mini_id, body)
    if cycle is None:
        raise HTTPException(status_code=404, detail="Artifact review cycle not found")
    return ArtifactReviewCycleRecord.model_validate(cycle)


@router.post("/trusted/{mini_id}/review-prediction", response_model=ReviewPredictionV1)
async def get_trusted_review_prediction(
    mini_id: str,
    body: ReviewPredictionRequestV1,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Build a structured review prediction for trusted service integrations."""
    result = await session.execute(select(Mini).where(Mini.id == mini_id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    return await _build_review_prediction_response(mini, body, session)


@router.post("/trusted/{mini_id}/artifact-review", response_model=ArtifactReviewV1)
async def get_trusted_artifact_review(
    mini_id: str,
    body: ArtifactReviewRequestV1,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_trusted_service),
):
    """Build a structured artifact review for trusted service integrations."""
    result = await session.execute(select(Mini).where(Mini.id == mini_id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    return await _build_artifact_review_response(mini, body, session)


@router.get("/{id}")
async def get_mini(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Get full mini details by ID."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    # Visibility check: private minis are owner-only
    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    # Owner gets full detail (including system prompt); others get public view
    if user is not None and user.id == mini.owner_id:
        return MiniDetail.model_validate(mini)
    return MiniPublic.model_validate(mini)


@router.post("/{id}/review-prediction", response_model=ReviewPredictionV1)
async def get_review_prediction(
    id: str,
    body: ReviewPredictionRequestV1,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Build a lightweight structured review prediction for a mini."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    require_mini_access(mini, user)
    return await _build_review_prediction_response(mini, body, session)


@router.post("/{id}/artifact-review", response_model=ArtifactReviewV1)
async def get_artifact_review(
    id: str,
    body: ArtifactReviewRequestV1,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Build a lightweight structured artifact review for a mini."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    require_mini_access(mini, user)
    return await _build_artifact_review_response(mini, body, session)


@router.get("/{id}/agreement-scorecard-summary", response_model=AgreementScorecardSummary)
async def get_agreement_scorecard_summary(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return the compact agreement scorecard summary for one mini."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    require_mini_owner(mini, user)

    cycle_result = await session.execute(
        select(ReviewCycle)
        .where(ReviewCycle.mini_id == mini.id)
        .where(ReviewCycle.human_review_outcome.isnot(None))
        .order_by(ReviewCycle.predicted_at.asc())
    )
    cycles = list(cycle_result.scalars().all())
    return build_agreement_scorecard_summary(mini, cycles)


@router.delete("/{id}", status_code=204)
async def delete_mini(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete a mini. Owner only."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    if mini.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this mini")
    await session.delete(mini)
    await session.commit()


@router.get("/{id}/status")
async def mini_status_stream(
    request: Request,
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """SSE stream of pipeline progress events."""
    from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

    ip = request.client.host if request.client else "unknown"
    check_mini_sse_ip_limit(ip)

    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if mini:
        require_mini_access(mini, user)
    queue = get_event_queue(id)

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                if event is None:
                    # Pipeline completed
                    yield {"event": "done", "data": "Pipeline completed"}
                    break
                yield {
                    "event": "progress",
                    "data": event.model_dump_json(),
                }
        except asyncio.TimeoutError:
            yield {"event": "timeout", "data": "Pipeline timed out"}
        finally:
            cleanup_event_queue(id)

    return EventSourceResponse(event_generator())


@router.get("/{id}/repos")
async def list_mini_repos(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List repos with their inclusion status for a mini. Owner only."""
    import json

    from app.models.ingestion_data import IngestionData, MiniRepoConfig

    # Get the mini
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    # Get cached repo data
    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == id,
            IngestionData.source_name == "github",
            IngestionData.data_key == "repos",
        )
    )
    cached = result.scalar_one_or_none()

    repos = []
    if cached:
        try:
            repos = json.loads(cached.data_json)
        except json.JSONDecodeError:
            # Invalid JSON in cache, use empty list
            pass

    # Get repo configs
    result = await session.execute(select(MiniRepoConfig).where(MiniRepoConfig.mini_id == id))
    configs = {c.repo_full_name: c.included for c in result.scalars().all()}

    return [
        {
            "name": r.get("name", ""),
            "full_name": r.get("full_name", ""),
            "language": r.get("language"),
            "stars": r.get("stargazers_count", 0),
            "description": r.get("description"),
            "included": configs.get(r.get("full_name", ""), True),
        }
        for r in repos
    ]


@router.get("/{id}/dataset")
async def get_mini_dataset(
    id: str,
    format: str = Query(default="jsonl", pattern="^jsonl$"),
    num_pairs: int = Query(default=20, ge=5, le=100),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Generate and download a DPO-style fine-tuning dataset for a mini.

    Requires the mini to exist with a soul document (spirit_content). Returns
    JSONL with instruction/chosen/rejected pairs formatted for QLoRA training.
    Rate-limited to one generation per mini per 10 minutes (in-memory).
    """
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if not mini.spirit_content:
        raise HTTPException(
            status_code=422,
            detail="Mini has no soul document — run the pipeline first before generating a dataset",
        )

    # In-memory rate limiting: one generation per mini per 10 minutes
    now = datetime.datetime.now(datetime.timezone.utc)
    last_gen = _dataset_rate_limit.get(id)
    if last_gen is not None:
        elapsed = (now - last_gen).total_seconds()
        if elapsed < _DATASET_RATE_LIMIT_SECONDS:
            retry_after = int(_DATASET_RATE_LIMIT_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Dataset generation rate-limited. Retry after {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    _dataset_rate_limit[id] = now

    from app.synthesis.dataset_generator import generate_dataset

    pairs = await generate_dataset(
        spirit_content=mini.spirit_content,
        memory_content=mini.memory_content or "",
        username=mini.username,
        num_pairs=num_pairs,
    )

    # Serialize as JSONL
    lines = [
        json.dumps(
            {
                "instruction": p.instruction,
                "chosen": p.chosen,
                "rejected": p.rejected,
                "skill_type": p.skill_type,
                "source": p.source,
                "example_id": p.example_id,
                "mini_id": id,
                "username": mini.username,
            },
            ensure_ascii=False,
        )
        for p in pairs
    ]
    jsonl_body = "\n".join(lines) + "\n"

    filename = f"{mini.username}_dpo_dataset.jsonl"
    return Response(
        content=jsonl_body,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Pair-Count": str(len(pairs)),
        },
    )


@router.get("/{id}/revisions")
async def list_mini_revisions(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List revision history for a mini. Owner only."""
    from app.models.revision import MiniRevision

    # Check ownership
    mini_result = await session.execute(select(Mini).where(Mini.id == id))
    mini = mini_result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    result = await session.execute(
        select(MiniRevision)
        .where(MiniRevision.mini_id == id)
        .order_by(MiniRevision.revision_number.desc())
    )
    revisions = result.scalars().all()
    return [
        {
            "id": r.id,
            "revision_number": r.revision_number,
            "trigger": r.trigger,
            "created_at": r.created_at,
        }
        for r in revisions
    ]


@router.get("/{id}/graph")
async def get_mini_graph(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Return the persisted KnowledgeGraph + PrinciplesMatrix for a mini.

    Implements ADR-001: structured skill/project/concept nodes and edges extracted
    during pipeline exploration. Public for public minis; private minis require auth.
    """
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if mini.knowledge_graph_json is None and mini.principles_json is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge graph not yet available — run the pipeline first",
        )

    return {
        "mini_id": mini.id,
        "username": mini.username,
        "knowledge_graph": mini.knowledge_graph_json or {"nodes": [], "edges": []},
        "principles": mini.principles_json or {"principles": []},
    }


@router.get("/{id}/revisions/{revision_id}")
async def get_mini_revision(
    id: str,
    revision_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Get full content of a specific revision. Owner only."""
    from app.models.revision import MiniRevision

    # Check ownership
    mini_result = await session.execute(select(Mini).where(Mini.id == id))
    mini = mini_result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    result = await session.execute(
        select(MiniRevision).where(
            MiniRevision.id == revision_id,
            MiniRevision.mini_id == id,
        )
    )
    revision = result.scalar_one_or_none()
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return {
        "id": revision.id,
        "mini_id": revision.mini_id,
        "revision_number": revision.revision_number,
        "spirit_content": revision.spirit_content,
        "memory_content": revision.memory_content,
        "system_prompt": revision.system_prompt,
        "values_json": revision.values_json,
        "trigger": revision.trigger,
        "created_at": revision.created_at,
    }


# ---------------------------------------------------------------------------
# Owner-only: frameworks-at-risk
# ---------------------------------------------------------------------------

#: Age threshold (days) for the low_evidence reason
_LOW_EVIDENCE_AGE_DAYS = 30

#: Minimum consecutive negative deltas to flag a declining_trend
_DECLINING_TREND_MIN_CONSECUTIVE = 3


def _build_at_risk_frameworks(
    principles_json: dict | None,
    mini_created_at: datetime.datetime | None = None,
) -> list[AtRiskFramework]:
    """Analyse decision frameworks and return those at risk.

    Three trigger reasons:
    - ``low_band``       — confidence < 0.3
    - ``declining_trend`` — 3+ consecutive negative deltas in confidence_history
    - ``low_evidence``   — revision == 0 AND mini is older than 30 days
    """
    import json as _json

    from app.synthesis.framework_views import CONFIDENCE_BAND_LOW, format_decision_frameworks

    if isinstance(principles_json, str):
        try:
            principles_json = _json.loads(principles_json)
        except Exception:
            return []

    all_frameworks = format_decision_frameworks(principles_json, include_retired=False)
    at_risk: list[AtRiskFramework] = []

    now = datetime.datetime.now(datetime.timezone.utc)
    mini_age_days: float | None = None
    if mini_created_at is not None:
        if mini_created_at.tzinfo is None:
            mini_created_at = mini_created_at.replace(tzinfo=datetime.timezone.utc)
        mini_age_days = (now - mini_created_at).days

    seen_ids: set[str] = set()

    for fw in all_frameworks:
        fid = fw["framework_id"]
        conf = fw["confidence"]
        rev = fw["revision"]
        history: list[dict] = fw.get("confidence_history") or []

        reason: str | None = None
        trend_summary: str | None = None

        # Reason 1: low_band
        if conf < CONFIDENCE_BAND_LOW:
            reason = "low_band"

        # Reason 2: declining_trend (3+ consecutive negative deltas)
        if reason is None and len(history) >= _DECLINING_TREND_MIN_CONSECUTIVE:
            recent = history[-_DECLINING_TREND_MIN_CONSECUTIVE:]
            all_negative = all(isinstance(e, dict) and float(e.get("delta", 0)) < 0 for e in recent)
            if all_negative:
                reason = "declining_trend"
                total_delta = sum(float(e.get("delta", 0)) for e in recent)
                cycles = len(recent)
                trend_summary = f"↘ {total_delta:+.2f} over {cycles} cycles"

        # Reason 3: low_evidence — revision == 0 and mini is old enough
        if reason is None and rev == 0:
            if mini_age_days is not None and mini_age_days > _LOW_EVIDENCE_AGE_DAYS:
                reason = "low_evidence"

        if reason is None:
            continue
        if fid in seen_ids:
            continue
        seen_ids.add(fid)

        at_risk.append(
            AtRiskFramework(
                framework_id=fid,
                condition=fw["condition"],
                action=fw["action"],
                value=fw["value"],
                confidence=conf,
                revision=rev,
                confidence_history=[],  # history parsed separately; keep payload lean
                reason=reason,
                trend_summary=trend_summary,
                retired=fw["retired"],
            )
        )

    return at_risk


@router.get("/{id}/frameworks-at-risk", response_model=list[AtRiskFramework])
async def get_frameworks_at_risk(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Return frameworks that need owner review (owner-only).

    A framework is at risk when any of these conditions holds:
    - ``low_band``       — confidence < 0.3 (LOW confidence band)
    - ``declining_trend`` — 3+ consecutive negative deltas in confidence history
    - ``low_evidence``   — never validated (revision == 0) and mini older than 30 days
    """
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    return _build_at_risk_frameworks(mini.principles_json, mini.created_at)


# ---------------------------------------------------------------------------
# Owner-only: retire a framework
# ---------------------------------------------------------------------------


@router.post("/{id}/frameworks/{framework_id}/retire", response_model=RetireFrameworkResponse)
async def retire_framework(
    id: str,
    framework_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Soft-delete a framework by setting ``retired: true`` in principles_json (owner-only).

    Retired frameworks are:
    - Excluded from the public decision-frameworks surface
    - Excluded from the system prompt DECISION FRAMEWORKS block
    - Excluded from review-predictor scoring (search_principles tool)
    - Still accessible via ``include_retired=True`` for audit purposes
    """
    import json as _json

    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    # Load principles_json
    p_json = mini.principles_json
    if isinstance(p_json, str):
        try:
            p_json = _json.loads(p_json)
        except Exception:
            p_json = {}
    if not isinstance(p_json, dict):
        p_json = {}

    df_payload = p_json.get("decision_frameworks")
    if not isinstance(df_payload, dict):
        raise HTTPException(status_code=404, detail="No decision frameworks found for this mini")

    raw_frameworks = df_payload.get("frameworks")
    if not isinstance(raw_frameworks, list):
        raise HTTPException(status_code=404, detail="No decision frameworks found for this mini")

    # Find and retire the matching framework
    found = False
    for fw in raw_frameworks:
        if not isinstance(fw, dict):
            continue
        if fw.get("framework_id") == framework_id:
            fw["retired"] = True
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail=f"Framework '{framework_id}' not found")

    # Write back
    updated_p_json = dict(p_json)
    updated_df = dict(df_payload)
    updated_df["frameworks"] = raw_frameworks
    updated_p_json["decision_frameworks"] = updated_df

    mini.principles_json = updated_p_json
    await session.commit()

    return RetireFrameworkResponse(
        framework_id=framework_id,
        retired=True,
        message=f"Framework '{framework_id}' has been retired.",
    )
