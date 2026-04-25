"""Minis MCP server.

Thin FastMCP wrapper around the Minis backend API.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastmcp import FastMCP

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 300.0
_AUTHOR_MODELS = {"junior_peer", "trusted_peer", "senior_peer", "unknown"}
_DELIVERY_CONTEXTS = {"hotfix", "normal", "exploratory", "incident"}

mcp = FastMCP(
    "minis",
    instructions=(
        "Create minis, inspect their profiles, and chat with them through the Minis backend API."
    ),
)


class BackendError(RuntimeError):
    """Raised when the Minis backend returns an error."""


class MiniNotFoundError(BackendError):
    """Raised when a mini cannot be resolved from an identifier."""


def _backend_url() -> str:
    return os.environ.get("MINIS_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def _auth_token() -> str:
    return os.environ.get("MINIS_AUTH_TOKEN", "").strip()


def _api(path: str) -> str:
    return f"{_backend_url()}/api{path}"


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True)


def _auth_headers(require_auth: bool) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = _auth_token()
    if require_auth and not token:
        raise BackendError(
            "MINIS_AUTH_TOKEN is required for this tool because the backend route is authenticated."
        )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
    require_auth: bool = False,
) -> Any:
    try:
        async with _make_client(
            timeout=httpx.Timeout(timeout, connect=DEFAULT_CONNECT_TIMEOUT_SECONDS)
        ) as client:
            response = await client.request(
                method,
                _api(path),
                json=json_body,
                headers=_auth_headers(require_auth),
            )
    except httpx.ConnectError as exc:
        raise BackendError(f"Cannot connect to Minis backend at {_backend_url()}") from exc

    if response.status_code >= 400:
        detail: Any = response.text
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail", detail)
        raise BackendError(f"{response.status_code} {detail}")

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


async def _resolve_mini_id(identifier: str) -> str:
    if _is_uuid(identifier):
        return identifier

    mini = await _request_json("GET", f"/minis/by-username/{quote(identifier, safe='')}")
    if not isinstance(mini, dict) or not mini.get("id"):
        raise MiniNotFoundError(f"Mini '{identifier}' could not be resolved to an id.")
    return str(mini["id"])


async def _fetch_mini(identifier: str) -> dict[str, Any]:
    if _is_uuid(identifier):
        path = f"/minis/{identifier}"
    else:
        path = f"/minis/by-username/{quote(identifier, safe='')}"

    mini = await _request_json("GET", path)
    if not isinstance(mini, dict):
        raise BackendError("Expected a mini object from the backend.")
    return mini


def _validate_review_prediction_input(
    *,
    title: str | None,
    description: str | None,
    diff_summary: str | None,
    changed_files: list[str] | None,
    author_model: str,
    delivery_context: str,
) -> None:
    if not any(
        [
            (title or "").strip(),
            (description or "").strip(),
            (diff_summary or "").strip(),
            changed_files or [],
        ]
    ):
        raise BackendError(
            "Provide at least one of title, description, diff_summary, or changed_files."
        )
    if author_model not in _AUTHOR_MODELS:
        raise BackendError(
            "author_model must be one of: junior_peer, trusted_peer, senior_peer, unknown."
        )
    if delivery_context not in _DELIVERY_CONTEXTS:
        raise BackendError(
            "delivery_context must be one of: hotfix, normal, exploratory, incident."
        )


def _signal_summary(signal: Any) -> dict[str, Any] | None:
    if not isinstance(signal, dict):
        return None
    result: dict[str, Any] = {
        "key": signal.get("key"),
        "summary": signal.get("summary"),
        "rationale": signal.get("rationale"),
        "confidence": signal.get("confidence"),
    }
    # Include framework attribution fields when present (additive, optional)
    if signal.get("framework_id") is not None:
        result["framework_id"] = signal["framework_id"]
    if signal.get("revision") is not None:
        result["revision"] = signal["revision"]
    return result


async def _stream_sse_events(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
    require_auth: bool = False,
) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    event_type = "message"
    data_lines: list[str] = []

    try:
        async with _make_client(
            timeout=httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                read=timeout_seconds,
                write=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                pool=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            )
        ) as client:
            async with client.stream(
                method,
                _api(path),
                json=json_body,
                headers={**_auth_headers(require_auth), "Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    detail = body.decode()
                    try:
                        payload = json.loads(detail)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        detail = payload.get("detail", detail)
                    raise BackendError(f"{response.status_code} {detail}")

                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            events.append((event_type, "\n".join(data_lines)))
                        event_type = "message"
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_type = line.removeprefix("event:").strip() or "message"
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.removeprefix("data:").lstrip())

                if data_lines:
                    events.append((event_type, "\n".join(data_lines)))
    except httpx.ConnectError as exc:
        raise BackendError(f"Cannot connect to Minis backend at {_backend_url()}") from exc
    except httpx.ReadTimeout as exc:
        raise BackendError(f"SSE request timed out after {timeout_seconds} seconds.") from exc

    return events


@mcp.tool()
async def list_sources() -> list[dict[str, Any]]:
    """List the ingestion sources that the backend currently exposes for mini creation."""

    sources = await _request_json("GET", "/minis/sources")
    if not isinstance(sources, list):
        raise BackendError("Expected a source list from the backend.")
    return sources


@mcp.tool()
async def create_mini(
    username: str,
    sources: list[str] | None = None,
    excluded_repos: list[str] | None = None,
    source_identifiers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create or regenerate a mini.

    This tool requires `MINIS_AUTH_TOKEN` because the backend route is authenticated.
    """

    result = await _request_json(
        "POST",
        "/minis",
        json_body={
            "username": username,
            "sources": sources or ["github"],
            "excluded_repos": excluded_repos or [],
            "source_identifiers": source_identifiers or {},
        },
        require_auth=True,
    )
    if not isinstance(result, dict):
        raise BackendError("Expected a mini summary object from the backend.")
    return result


@mcp.tool()
async def list_minis(mine: bool = False) -> list[dict[str, Any]]:
    """List public minis, or your own minis when `mine=true` and auth is configured."""

    result = await _request_json(
        "GET",
        f"/minis?mine={'true' if mine else 'false'}",
        require_auth=mine,
    )
    if not isinstance(result, list):
        raise BackendError("Expected a mini list from the backend.")
    return result


@mcp.tool()
async def get_mini(identifier: str) -> dict[str, Any]:
    """Fetch a mini by UUID or username."""

    return await _fetch_mini(identifier)


@mcp.tool()
async def get_mini_status(
    identifier: str,
    timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Read pipeline progress events for a mini until completion or timeout."""

    mini_id = await _resolve_mini_id(identifier)
    events = await _stream_sse_events(
        "GET",
        f"/minis/{mini_id}/status",
        timeout_seconds=timeout_seconds,
    )

    parsed: list[dict[str, Any]] = []
    for event_type, data in events:
        if event_type == "progress":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"raw": data}
            if isinstance(payload, dict):
                payload["event"] = event_type
                parsed.append(payload)
            else:
                parsed.append({"event": event_type, "data": payload})
            continue
        parsed.append({"event": event_type, "data": data})
        if event_type in {"done", "timeout"}:
            break
    return parsed


@mcp.tool()
async def chat_with_mini(
    identifier: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    conversation_id: str | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Chat with a mini and return the assembled response text.

    Use `conversation_id` from a prior response to continue an authenticated conversation.
    """

    mini_id = await _resolve_mini_id(identifier)
    events = await _stream_sse_events(
        "POST",
        f"/minis/{mini_id}/chat",
        json_body={
            "message": message,
            "history": history or [],
            "conversation_id": conversation_id,
        },
        timeout_seconds=timeout_seconds,
    )

    response_chunks: list[str] = []
    resolved_conversation_id = conversation_id
    for event_type, data in events:
        if event_type == "conversation_id":
            resolved_conversation_id = data
            continue
        if event_type == "chunk":
            response_chunks.append(data)
            continue
        if event_type == "error":
            raise BackendError(data)

    return {
        "mini_id": mini_id,
        "conversation_id": resolved_conversation_id,
        "response": "".join(response_chunks),
    }


@mcp.tool()
async def get_mini_graph(identifier: str) -> dict[str, Any]:
    """Fetch the persisted knowledge graph and principles data for a mini."""

    mini_id = await _resolve_mini_id(identifier)
    result = await _request_json("GET", f"/minis/{mini_id}/graph")
    if not isinstance(result, dict):
        raise BackendError("Expected a graph payload from the backend.")
    return result


@mcp.tool()
async def predict_review(
    identifier: str,
    title: str | None = None,
    description: str | None = None,
    diff_summary: str | None = None,
    changed_files: list[str] | None = None,
    repo_name: str | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> dict[str, Any]:
    """Predict what a mini would likely block on for a proposed change.

    Provide at least one of `title`, `description`, `diff_summary`, or `changed_files`.
    Public minis work without auth. Private minis require `MINIS_AUTH_TOKEN`.
    """

    _validate_review_prediction_input(
        title=title,
        description=description,
        diff_summary=diff_summary,
        changed_files=changed_files,
        author_model=author_model,
        delivery_context=delivery_context,
    )

    mini_id = await _resolve_mini_id(identifier)
    result = await _request_json(
        "POST",
        f"/minis/{mini_id}/review-prediction",
        json_body={
            "repo_name": repo_name,
            "title": title,
            "description": description,
            "diff_summary": diff_summary,
            "changed_files": changed_files or [],
            "author_model": author_model,
            "delivery_context": delivery_context,
        },
    )
    if not isinstance(result, dict):
        raise BackendError("Expected a structured review prediction from the backend.")

    private_assessment = result.get("private_assessment", {})
    expressed_feedback = result.get("expressed_feedback", {})
    delivery_policy = result.get("delivery_policy", {})

    blockers = []
    for signal in private_assessment.get("blocking_issues", []):
        summarized = _signal_summary(signal)
        if summarized:
            blockers.append(summarized)

    open_questions = []
    for signal in private_assessment.get("open_questions", []):
        summarized = _signal_summary(signal)
        if summarized:
            open_questions.append(summarized)

    return {
        "mini_id": mini_id,
        "reviewer_username": result.get("reviewer_username"),
        "approval_state": expressed_feedback.get("approval_state"),
        "summary": expressed_feedback.get("summary"),
        "likely_blockers": blockers,
        "open_questions": open_questions,
        "delivery_policy": delivery_policy if isinstance(delivery_policy, dict) else {},
        "prediction": result,
    }


_BADGE_HIGH_THRESHOLD = 0.7
_BADGE_LOW_THRESHOLD = 0.3


def _framework_badge(confidence: float) -> str | None:
    """Return badge label matching the GitHub App review comment convention."""
    if confidence > _BADGE_HIGH_THRESHOLD:
        return "high"
    if confidence < _BADGE_LOW_THRESHOLD:
        return "low"
    return None


@mcp.tool()
async def get_decision_frameworks(
    username: str,
    min_confidence: float = 0.0,
    limit: int = 20,
) -> dict[str, Any]:
    """Return the learned decision-framework profile for a mini.

    Frameworks are sorted by confidence (descending), then revision (descending).
    Each entry includes a ``badge`` field — ``"high"`` (confidence > 0.7),
    ``"low"`` (confidence < 0.3), or ``null`` — matching the GitHub App badge
    convention.

    When the mini has no framework profile yet the response contains an empty
    ``frameworks`` list and a ``note`` rather than an error.

    Args:
        username: GitHub username or mini UUID.
        min_confidence: Exclude frameworks below this threshold (0.0–1.0).
        limit: Maximum number of frameworks to return (default 20).
    """

    mini = await _fetch_mini(username)

    principles_json: dict[str, Any] | None = mini.get("principles_json") or mini.get("principles")

    # Defensive: also accept a nested payload that a future ALLIE-461 endpoint
    # might expose as {"decision_frameworks": {...}} at the top level.
    if isinstance(principles_json, dict) and "frameworks" in principles_json and "version" in principles_json:
        # Already looks like a DecisionFrameworkProfile — wrap it.
        df_payload = principles_json
    elif isinstance(principles_json, dict):
        df_payload = principles_json.get("decision_frameworks") or {}
    else:
        df_payload = {}

    raw_frameworks: list[Any] = df_payload.get("frameworks", []) if isinstance(df_payload, dict) else []

    if not raw_frameworks:
        return {
            "username": mini.get("username", username),
            "frameworks": [],
            "summary": {"total": 0, "mean_confidence": 0.0, "max_revision": 0},
            "note": "no framework profile yet",
        }

    # Filter by min_confidence
    filtered = [
        fw for fw in raw_frameworks
        if isinstance(fw, dict) and fw.get("confidence", 0.0) >= min_confidence
    ]

    # Sort: confidence desc, then revision desc
    filtered.sort(key=lambda fw: (-fw.get("confidence", 0.0), -fw.get("revision", 0)))

    # Apply limit
    filtered = filtered[:limit]

    # Build structured output
    out_frameworks: list[dict[str, Any]] = []
    for fw in filtered:
        conf: float = fw.get("confidence", 0.0)
        out_frameworks.append(
            {
                "framework_id": fw.get("framework_id"),
                "confidence": conf,
                "revision": fw.get("revision", 0),
                # Map schema fields to the CLI-style names used in badges/display
                "trigger": fw.get("condition") or fw.get("trigger"),
                "action": fw.get("block_policy") or fw.get("approval_policy") or fw.get("action"),
                "value": (
                    fw.get("value_ids", [None])[0]
                    if fw.get("value_ids")
                    else fw.get("value")
                ),
                "badge": _framework_badge(conf),
            }
        )

    total = len(out_frameworks)
    mean_conf = sum(fw["confidence"] for fw in out_frameworks) / total if total else 0.0
    max_rev = max((fw["revision"] for fw in out_frameworks), default=0)

    return {
        "username": mini.get("username", username),
        "frameworks": out_frameworks,
        "summary": {
            "total": total,
            "mean_confidence": round(mean_conf, 4),
            "max_revision": max_rev,
        },
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
