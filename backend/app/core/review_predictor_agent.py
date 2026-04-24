import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent import AgentTool, run_agent
from app.models.mini import Mini
from app.models.schemas import (
    ReviewPredictionV1,
    ReviewPredictionRequestV1,
)

logger = logging.getLogger(__name__)

async def predict_review(
    mini: Mini,
    body: ReviewPredictionRequestV1,
    session: AsyncSession,
) -> ReviewPredictionV1:
    """Predict a review for a given artifact request using an LLM agent."""

    # 1. Build search tools (adapted from chat.py)
    tools = _build_predictor_tools(mini, session)

    # 2. Construct the system prompt using the "Three Layer Model"
    system_prompt = _build_predictor_system_prompt(mini, body)

    # 3. Construct the user prompt (the artifact detail)
    user_prompt = _build_predictor_user_prompt(body)

    # 4. Run the agent
    # We ask for a structured JSON response
    system_prompt += (
        "\n\n# OUTPUT FORMAT\n"
        "You MUST return a single JSON object matching the `ReviewPredictionV1` schema. "
        "Do not include any other text before or after the JSON.\n"
        "The JSON must have the following structure:\n"
        "{\n"
        '  "version": "review_prediction_v1",\n'
        '  "reviewer_username": "...",\n'
        '  "repo_name": "...",\n'
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
        # Fallback to heuristic-based if agent fails
        from app.core.review_prediction import build_review_prediction_v1
        logger.warning("Review predictor agent failed to return a response; falling back to heuristic.")
        return build_review_prediction_v1(mini, body)

    try:
        # Try to find JSON in the response if there's fluff
        json_start = result.final_response.find("{")
        json_end = result.final_response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = result.final_response[json_start:json_end]
            data = json.loads(json_str)
            return ReviewPredictionV1.model_validate(data)
        else:
            raise ValueError("No JSON found in agent response")
    except Exception as e:
        logger.error("Failed to parse agent review prediction: %s", e)
        from app.core.review_prediction import build_review_prediction_v1
        return build_review_prediction_v1(mini, body)

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

        principles = p_data.get("principles", [])
        query_lower = query.lower()
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            keywords = [query_lower]

        matching: list[dict] = []
        for p in principles:
            p_str = f"{p.get('trigger', '')} {p.get('action', '')} {p.get('value', '')}".lower()
            score = sum(1 for kw in keywords if kw in p_str)
            if score > 0:
                matching.append({**p, "_score": score})

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
            parts.append(f"- **Trigger**: {trigger}\n  **Action**: {action}\n  **Value**: {value} (Intensity: {intensity:.1f})")

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

def _build_predictor_system_prompt(mini: Mini, body: ReviewPredictionRequestV1) -> str:
    """Build the system prompt for the review predictor agent."""
    
    # Start with the mini's core identity prompt
    base_prompt = mini.system_prompt or ""
    
    review_directives = (
        "\n\n# REVIEW PREDICTOR DIRECTIVES\n"
        "Your task is to predict how you, as the developer described above, would review a specific engineering artifact. "
        "You must use the 'Three Layer Model' for your prediction:\n\n"
        "## 1. Private Assessment (What you think)\n"
        "- What do you REALLY think about this artifact?\n"
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
        "1. **THINK** about the artifact and who the author is.\n"
        "2. **SEARCH** your memories, evidence, and principles for your stance on the technologies or patterns in the artifact.\n"
        "3. **ASSESS** the artifact privately.\n"
        "4. **DETERMINE** your delivery policy.\n"
        "5. **GENERATE** the expressed feedback.\n"
    ).format(
        author_model=body.author_model,
        delivery_context=body.delivery_context,
    )
    
    return base_prompt + review_directives

def _build_predictor_user_prompt(body: ReviewPredictionRequestV1) -> str:
    """Build the user prompt containing the artifact details."""
    parts = [f"# {body.artifact_type.replace('_', ' ').upper()} TO REVIEW\n"]
    if body.repo_name:
        parts.append(f"Repo: {body.repo_name}")
    if body.title:
        parts.append(f"Title: {body.title}")
    if body.description:
        parts.append(f"Description:\n{body.description}")
    if body.artifact_summary:
        parts.append(f"Artifact Summary:\n{body.artifact_summary}")
    if body.changed_files:
        parts.append(f"Changed Files: {', '.join(body.changed_files)}")
    if body.diff_summary:
        parts.append(f"Diff Summary:\n{body.diff_summary}")
        
    parts.append(f"\nAuthor Relationship: {body.author_model}")
    parts.append(f"Delivery Context: {body.delivery_context}")
    
    return "\n".join(parts)
