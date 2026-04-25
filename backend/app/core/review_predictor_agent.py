import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent import AgentTool, run_agent
from app.core.review_prediction import load_same_repo_precedent, render_same_repo_precedent_text
from app.models.mini import Mini
from app.models.schemas import (
    ArtifactReviewRequestBaseV1,
    ArtifactReviewV1,
    ReviewPredictionRequestV1,
    ReviewPredictionV1,
)

logger = logging.getLogger(__name__)

async def _predict_artifact_review(
    mini: Mini,
    body: ArtifactReviewRequestBaseV1,
    session: AsyncSession,
    *,
    response_model: type[ArtifactReviewV1],
    response_schema_name: str,
    artifact_label: str,
    fallback_builder,
    same_repo_precedent: dict | None = None,
) -> ArtifactReviewV1:
    """Predict an artifact review for a given request using an LLM agent."""
    # 1. Build search tools (adapted from chat.py)
    tools = _build_predictor_tools(mini, session)

    # 2. Construct the system prompt using the "Three Layer Model"
    system_prompt = _build_predictor_system_prompt(
        mini,
        body,
        artifact_label=artifact_label,
        same_repo_precedent=same_repo_precedent,
    )

    # 3. Construct the user prompt (the artifact detail)
    user_prompt = _build_predictor_user_prompt(
        body,
        artifact_label=artifact_label,
        same_repo_precedent=same_repo_precedent,
    )

    # 4. Run the agent
    system_prompt += (
        "\n\n# OUTPUT FORMAT\n"
        f"You MUST return a single JSON object matching the `{response_schema_name}` schema. "
        "Do not include any other text before or after the JSON.\n"
        "The JSON must have the following structure:\n"
        "{\n"
        f'  "version": "{response_model.model_fields["version"].default}",\n'
        '  "reviewer_username": "...",\n'
        '  "repo_name": "...",\n'
        '  "artifact_summary": {"artifact_type": "...", "title": "..."},\n'
        '  "private_assessment": {\n'
        '    "blocking_issues": [{"key": "...", "summary": "...", "rationale": "...", "confidence": 0.0, "evidence": []}],\n'
        '    "non_blocking_issues": [...],\n'
        '    "open_questions": [...],\n'
        '    "positive_signals": [...],\n'
        '    "confidence": 0.0\n'
        '  },\n'
        '  "delivery_policy": {\n'
        '    "author_model": "...",\n'
        '    "context": "...",\n'
        '    "strictness": "...",\n'
        '    "teaching_mode": true/false,\n'
        '    "shield_author_from_noise": true/false,\n'
        '    "rationale": "..."\n'
        '  },\n'
        '  "expressed_feedback": {\n'
        '    "summary": "...",\n'
        '    "comments": [{"type": "...", "disposition": "...", "issue_key": "...", "summary": "...", "rationale": "..."}],\n'
        '    "approval_state": "..."\n'
        '  }\n'
        "}\n"
    )

    result = await run_agent(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=tools,
        max_turns=10,
    )

    if not result.final_response:
        logger.warning("Review predictor agent failed to return a response; falling back to heuristic.")
        return fallback_builder(mini, body)

    try:
        json_start = result.final_response.find("{")
        json_end = result.final_response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = result.final_response[json_start:json_end]
            data = json.loads(json_str)
            return response_model.model_validate(data)
        raise ValueError("No JSON found in agent response")
    except Exception as e:
        logger.error("Failed to parse agent review prediction: %s", e)
        return fallback_builder(mini, body)


async def predict_review(
    mini: Mini,
    body: ReviewPredictionRequestV1,
    session: AsyncSession,
) -> ReviewPredictionV1:
    """Predict a review for a given PR request using an LLM agent."""
    same_repo_precedent = await load_same_repo_precedent(
        session,
        getattr(mini, "id", None),
        body.repo_name,
    )

    from app.core.review_prediction import build_review_prediction_v1

    return await _predict_artifact_review(
        mini,
        body,
        session,
        response_model=ReviewPredictionV1,
        response_schema_name="ReviewPredictionV1",
        artifact_label="Pull Request",
        fallback_builder=lambda current_mini, current_body: build_review_prediction_v1(
            current_mini,
            current_body,
            same_repo_precedent=same_repo_precedent,
        ),
        same_repo_precedent=same_repo_precedent,
    )


async def predict_artifact_review(
    mini: Mini,
    body: ArtifactReviewRequestBaseV1,
    session: AsyncSession,
) -> ArtifactReviewV1:
    """Predict a non-PR artifact review using an LLM agent."""
    from app.core.review_prediction import build_artifact_review_v1

    return await _predict_artifact_review(
        mini,
        body,
        session,
        response_model=ArtifactReviewV1,
        response_schema_name="ArtifactReviewV1",
        artifact_label=body.artifact_type.replace("_", " ").title(),
        fallback_builder=build_artifact_review_v1,
    )

def _build_predictor_tools(mini: Mini, session: AsyncSession) -> list[AgentTool]:
    """Build the tools available to the predictor agent."""

    def _keyword_search(content: str, query: str, max_results: int = 5) -> str:
        lines = content.split("\n")
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            keywords = [query.lower()]

        scored: list[tuple[int, int]] = []
        for i, line in enumerate(lines):
            line_lower = line.lower()
            score = sum(1 for kw in keywords if kw in line_lower)
            if score > 0:
                scored.append((score, i))

        scored.sort(key=lambda x: x[0], reverse=True)

        seen_ranges: set[int] = set()
        results: list[str] = []
        for _score, idx in scored:
            if idx in seen_ranges:
                continue
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            for j in range(start, end):
                seen_ranges.add(j)
            context = "\n".join(lines[start:end])
            results.append(context)
            if len(results) >= max_results:
                break

        return "\n\n---\n\n".join(results) if results else ""

    async def search_memories(query: str) -> str:
        """Search the mini's memory bank for facts, opinions, or expertise."""
        if not mini.memory_content:
            return "No memories available."
        result = _keyword_search(mini.memory_content, query)
        return result or f"No memories found matching '{query}'."

    async def search_evidence(query: str) -> str:
        """Search raw evidence (code reviews, commits, PRs) for quotes and examples."""
        if not mini.evidence_cache:
            return "No evidence available."
        result = _keyword_search(mini.evidence_cache, query)
        return result or f"No evidence found matching '{query}'."

    async def search_principles(query: str) -> str:
        """Search the principles matrix for decision rules and engineering values."""
        if not mini.principles_json:
            return "No principles available."

        try:
            p_data = (
                mini.principles_json
                if isinstance(mini.principles_json, dict)
                else json.loads(mini.principles_json)
            )
        except (json.JSONDecodeError, TypeError):
            return "Principles data is corrupted."

        # Build confidence index from decision_frameworks payload (may be absent for
        # older minis that were synthesized before the framework-delta loop shipped).
        # Retired frameworks are excluded from scoring.
        confidence_index: dict[str, tuple[float, int]] = {}
        retired_framework_ids: set[str] = set()
        df_payload = p_data.get("decision_frameworks") or {}
        for fw in (df_payload.get("frameworks") or []):
            fid = fw.get("framework_id")
            if fid:
                if fw.get("retired", False):
                    retired_framework_ids.add(fid)
                    continue
                confidence_index[fid] = (
                    float(fw.get("confidence", 0.5)),
                    int(fw.get("revision", 0)),
                )

        principles = p_data.get("principles", [])
        keywords = [w.lower() for w in query.split() if len(w) > 1] or [query.lower()]

        def _confidence_modifier(fid: str | None) -> float:
            if fid is None or fid not in confidence_index:
                return 0.0
            conf, rev = confidence_index[fid]
            if conf < 0.3:
                return -0.5
            if conf > 0.7:
                raw = 0.3 + rev * 0.05
                return min(raw, 0.5)
            return 0.0

        matching: list[dict] = []
        for p in principles:
            # Skip retired frameworks — they should not influence scoring
            fid = p.get("framework_id")
            if fid and fid in retired_framework_ids:
                continue
            p_str = f"{p.get('trigger', '')} {p.get('action', '')} {p.get('value', '')}".lower()
            kw_score = sum(1 for kw in keywords if kw in p_str)
            if kw_score == 0:
                continue
            total_score = kw_score + _confidence_modifier(fid)
            matching.append({**p, "_score": total_score, "_fid": fid})

        matching.sort(key=lambda x: x["_score"], reverse=True)
        matching = matching[:10]

        if not matching:
            return f"No principles found matching '{query}'."

        parts = []
        for p in matching:
            trigger = p.get("trigger", "Unknown")
            action = p.get("action", "Unknown")
            value = p.get("value", "Unknown")
            intensity = p.get("intensity", 0.5)
            fid = p.get("_fid")
            badge = ""
            validated_badge = ""
            if fid and fid in confidence_index:
                conf, rev = confidence_index[fid]
                if conf > 0.7:
                    badge = " [HIGH CONFIDENCE ✓]"
                elif conf < 0.3:
                    badge = " [LOW CONFIDENCE ⚠]"
                if rev > 0:
                    validated_badge = f" [validated {rev} time{'s' if rev != 1 else ''}]"
            parts.append(
                f"- **Trigger**: {trigger}\n"
                f"  **Action**: {action}\n"
                f"  **Value**: {value} (Intensity: {intensity:.1f}){badge}{validated_badge}"
            )

        return "\n\n".join(parts)

    async def think(reasoning: str) -> str:
        """Internal reasoning step -- work through a problem before responding."""
        return "OK"

    return [
        AgentTool(
            name="search_memories",
            description="Search memory bank for facts, opinions, and projects.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=search_memories,
        ),
        AgentTool(
            name="search_evidence",
            description="Search raw evidence for quotes and examples.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=search_evidence,
        ),
        AgentTool(
            name="search_principles",
            description="Search principles matrix for decision rules and values.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=search_principles,
        ),
        AgentTool(
            name="think",
            description="Think through the problem step by step.",
            parameters={
                "type": "object",
                "properties": {"reasoning": {"type": "string"}},
                "required": ["reasoning"],
            },
            handler=think,
        ),
    ]

def _build_predictor_system_prompt(
    mini: Mini,
    body: ArtifactReviewRequestBaseV1,
    *,
    artifact_label: str,
    same_repo_precedent: dict | None = None,
) -> str:
    """Build the system prompt for the review predictor agent."""
    
    # Start with the mini's core identity prompt
    base_prompt = mini.system_prompt or ""
    
    review_directives = (
        "\n\n# REVIEW PREDICTOR DIRECTIVES\n"
        f"Your task is to predict how you, as the developer described above, would review a specific {artifact_label}. "
        "You must use the 'Three Layer Model' for your prediction:\n\n"
        "## 1. Private Assessment (What you think)\n"
        f"- What do you REALLY think about this {body.artifact_type.replace('_', ' ')}?\n"
        "- What are the blocking risks? What are the positive signs?\n"
        "- Be brutally honest with yourself here. Use your core engineering values and principles.\n\n"
        "## 2. Delivery Policy (How you choose to say it)\n"
        "- Based on the relationship with the author and the context, how will you deliver your feedback?\n"
        "- Author Relationship: {author_model} (Senior Peer, Junior Peer, Trusted Peer, etc.)\n"
        "- Delivery Context: {delivery_context} (Normal, Hotfix, Incident, Exploratory)\n"
        "- Should you be blunt? Coaching-oriented? Should you shield them from noise (nits)?\n"
        "- A Hotfix or Incident context usually means you focus ONLY on critical correctness and unblocking.\n"
        "- A Junior Peer usually means more coaching and explanation.\n"
        "- A Senior Peer usually means you can be more direct and assume more shared context.\n\n"
        "## 3. Expressed Feedback (What you actually say)\n"
        "- This is the final result: the summary message and specific comments.\n"
        "- Your expressed feedback MUST follow your delivery policy.\n"
        "- If you think there's a risk but your policy is to 'shield from noise', you might not mention it if it's minor.\n\n"
        "# REQUIRED WORKFLOW\n"
        f"1. **THINK** about the {body.artifact_type.replace('_', ' ')} and who the author is.\n"
        f"2. **SEARCH** your memories, evidence, and principles for your stance on the technologies or patterns in the {body.artifact_type.replace('_', ' ')}.\n"
        f"3. **ASSESS** the {body.artifact_type.replace('_', ' ')} privately.\n"
        "4. **DETERMINE** your delivery policy.\n"
        "5. **GENERATE** the expressed feedback.\n"
        "6. **CALIBRATE** the private assessment and delivery policy with any explicitly provided precedent before writing expressed feedback.\n"
    ).format(
        author_model=body.author_model,
        delivery_context=body.delivery_context,
    )
    precedent_text = render_same_repo_precedent_text(same_repo_precedent)
    if precedent_text:
        review_directives += f"\nSame-repo review precedent: {precedent_text}\n"

    return base_prompt + review_directives

def _build_predictor_user_prompt(
    body: ArtifactReviewRequestBaseV1,
    *,
    artifact_label: str,
    same_repo_precedent: dict | None = None,
) -> str:
    """Build the user prompt containing the artifact details."""
    parts = [f"# {artifact_label.upper()} TO REVIEW\n"]
    if body.repo_name:
        parts.append(f"Repo: {body.repo_name}")
    if body.title:
        parts.append(f"Title: {body.title}")
    if body.description:
        parts.append(f"Description:\n{body.description}")
    if body.artifact_summary:
        parts.append(f"Artifact Summary:\n{body.artifact_summary}")
    if body.diff_summary:
        parts.append(f"Diff Summary:\n{body.diff_summary}")
    if body.changed_files:
        parts.append(f"Changed Files: {', '.join(body.changed_files)}")
    precedent_text = render_same_repo_precedent_text(same_repo_precedent)
    if precedent_text:
        parts.append(f"Same-Repo Precedent:\n{precedent_text}")
        
    parts.append(f"\nAuthor Relationship: {body.author_model}")
    parts.append(f"Delivery Context: {body.delivery_context}")
    
    return "\n".join(parts)
