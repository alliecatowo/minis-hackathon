"""Minis MCP server.

Thin FastMCP wrapper around the Minis backend API.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastmcp import FastMCP

DEFAULT_BACKEND_URL = "https://minis.fly.dev"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 300.0
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "minis" / "mcp-token"
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
    env_token = os.environ.get("MINIS_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    token_file = Path(os.environ.get("MINIS_AUTH_TOKEN_FILE", str(DEFAULT_TOKEN_PATH))).expanduser()
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise BackendError(f"Unable to read MINIS auth token file at {token_file}") from exc


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


def _token_path() -> Path:
    return Path(os.environ.get("MINIS_AUTH_TOKEN_FILE", str(DEFAULT_TOKEN_PATH))).expanduser()


def _write_auth_token(token: str) -> Path:
    token_path = _token_path()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(token.strip() + "\n", encoding="utf-8")
    token_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return token_path


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


async def _github_device_config() -> dict[str, str]:
    result = await _request_json("GET", "/auth/github-device/config", timeout=10.0)
    if not isinstance(result, dict) or not result.get("client_id"):
        raise BackendError("Backend did not return a GitHub device auth client_id.")
    return {"client_id": str(result["client_id"]), "scope": str(result.get("scope") or "read:user")}


async def _request_github_device_code(client_id: str, scope: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        response = await client.post(
            "https://github.com/login/device/code",
            data={"client_id": client_id, "scope": scope},
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        raise BackendError(f"GitHub device-code request failed: {response.status_code}")
    payload = response.json()
    required = {"device_code", "user_code", "verification_uri", "expires_in", "interval"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise BackendError("GitHub device-code response omitted required fields.")
    return payload


async def _poll_github_device_token(
    *,
    client_id: str,
    device_code: str,
    expires_in: int,
    interval: int,
) -> str:
    deadline = time.monotonic() + expires_in
    poll_interval = max(interval, 1)

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            if response.status_code >= 400:
                raise BackendError(f"GitHub token polling failed: {response.status_code}")
            payload = response.json()
            if payload.get("access_token"):
                return str(payload["access_token"])

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                poll_interval += 5
                continue
            if error == "access_denied":
                raise BackendError("GitHub device authorization was denied.")
            if error == "expired_token":
                raise BackendError("GitHub device authorization expired.")
            raise BackendError(f"GitHub device authorization failed: {error or payload}")

    raise BackendError("GitHub device authorization expired.")


async def _exchange_github_token_for_minis_token(github_access_token: str) -> dict[str, Any]:
    result = await _request_json(
        "POST",
        "/auth/github-device/exchange",
        json_body={"access_token": github_access_token},
        timeout=20.0,
    )
    if not isinstance(result, dict) or not result.get("access_token"):
        raise BackendError("Backend did not return a Minis access_token.")
    return result


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


def _review_prediction_unavailable_reason(result: dict[str, Any]) -> str | None:
    required = {"prediction_available", "mode", "unavailable_reason"}
    if not required.issubset(result):
        return "backend response omitted review prediction availability contract"

    if result.get("prediction_available") is False or result.get("mode") == "gated":
        return str(result.get("unavailable_reason") or "review prediction is gated")

    if result.get("prediction_available") is not True:
        return "backend response returned invalid prediction_available value"
    if result.get("mode") != "llm":
        return f"backend response returned unsupported review prediction mode: {result.get('mode')}"
    if result.get("unavailable_reason") is not None:
        return "backend response returned unavailable_reason for available prediction"
    return None


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
    minis = result.get("data") if isinstance(result, dict) else result
    if not isinstance(minis, list):
        raise BackendError("Expected a mini list from the backend.")
    return minis


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

    unavailable_reason = _review_prediction_unavailable_reason(result)
    if unavailable_reason:
        return {
            "mini_id": mini_id,
            "reviewer_username": result.get("reviewer_username"),
            "prediction_available": False,
            "mode": "gated",
            "unavailable_reason": unavailable_reason,
            "approval_state": "uncertain",
            "summary": result.get("expressed_feedback", {}).get("summary")
            if isinstance(result.get("expressed_feedback"), dict)
            else None,
            "likely_blockers": [],
            "open_questions": [],
            "delivery_policy": result.get("delivery_policy")
            if isinstance(result.get("delivery_policy"), dict)
            else {},
            "prediction": result,
        }

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
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": result.get("unavailable_reason"),
        "approval_state": expressed_feedback.get("approval_state"),
        "summary": expressed_feedback.get("summary"),
        "likely_blockers": blockers,
        "open_questions": open_questions,
        "delivery_policy": delivery_policy if isinstance(delivery_policy, dict) else {},
        "prediction": result,
    }


@mcp.tool()
async def advise_patch(
    identifier: str,
    title: str | None = None,
    description: str | None = None,
    diff_summary: str | None = None,
    changed_files: list[str] | None = None,
    repo_name: str | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> dict[str, Any]:
    """Turn a mini's decision frameworks into patch guidance for a coding agent.

    The tool returns explicit guidance on what to change, what not to change,
    risks, expected reviewer objections, and framework/evidence provenance.
    If the mini has no decision-framework evidence yet, the response is gated
    instead of falling back to generic coding advice.
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
        f"/minis/{mini_id}/patch-advisor",
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
        raise BackendError("Expected a structured patch advisor artifact from the backend.")

    if result.get("advice_available") is False or result.get("mode") == "gated":
        return {
            "mini_id": mini_id,
            "reviewer_username": result.get("reviewer_username"),
            "advice_available": False,
            "mode": result.get("mode", "gated"),
            "unavailable_reason": result.get("unavailable_reason")
            or "patch advisor is gated",
            "change_plan": [],
            "do_not_change": [],
            "risks": [],
            "expected_reviewer_objections": [],
            "evidence_references": [],
            "advisor": result,
        }

    return {
        "mini_id": mini_id,
        "reviewer_username": result.get("reviewer_username"),
        "advice_available": result.get("advice_available", True),
        "mode": result.get("mode", "framework"),
        "unavailable_reason": result.get("unavailable_reason"),
        "change_plan": result.get("change_plan", []),
        "do_not_change": result.get("do_not_change", []),
        "risks": result.get("risks", []),
        "expected_reviewer_objections": result.get(
            "expected_reviewer_objections",
            [],
        ),
        "evidence_references": result.get("evidence_references", []),
        "framework_signals": result.get("framework_signals", []),
        "advisor": result,
    }


def _comment_summary(comment: Any) -> dict[str, Any] | None:
    if not isinstance(comment, dict):
        return None
    return {
        "type": comment.get("type"),
        "disposition": comment.get("disposition"),
        "issue_key": comment.get("issue_key"),
        "summary": comment.get("summary"),
        "rationale": comment.get("rationale"),
    }


@mcp.tool()
async def advise_coding_changes(
    identifier: str,
    title: str | None = None,
    description: str | None = None,
    diff_summary: str | None = None,
    changed_files: list[str] | None = None,
    repo_name: str | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> dict[str, Any]:
    """Turn a mini's review prediction into coding-session guidance.

    The tool does not invent advice. It returns unavailable/gated unless the
    review-prediction backend returns an available structured prediction.
    """

    prediction = await predict_review.fn(
        identifier,
        title=title,
        description=description,
        diff_summary=diff_summary,
        changed_files=changed_files,
        repo_name=repo_name,
        author_model=author_model,
        delivery_context=delivery_context,
    )

    if not prediction.get("prediction_available"):
        return {
            "mini_id": prediction.get("mini_id"),
            "reviewer_username": prediction.get("reviewer_username"),
            "guidance_available": False,
            "mode": "gated",
            "unavailable_reason": prediction.get("unavailable_reason"),
            "change_plan": [],
            "questions_to_answer": [],
            "prediction": prediction.get("prediction"),
        }

    raw_prediction = prediction.get("prediction") if isinstance(prediction.get("prediction"), dict) else {}
    expressed_feedback = raw_prediction.get("expressed_feedback", {})
    comments = expressed_feedback.get("comments", []) if isinstance(expressed_feedback, dict) else []

    change_plan: list[dict[str, Any]] = []
    for blocker in prediction.get("likely_blockers", []):
        if isinstance(blocker, dict):
            change_plan.append(
                {
                    "priority": "blocker",
                    "issue_key": blocker.get("key"),
                    "action": blocker.get("summary"),
                    "rationale": blocker.get("rationale"),
                    "framework_id": blocker.get("framework_id"),
                    "confidence": blocker.get("confidence"),
                }
            )

    for comment in comments:
        summarized = _comment_summary(comment)
        if summarized and summarized["type"] in {"blocker", "note"}:
            change_plan.append(
                {
                    "priority": summarized["type"],
                    "issue_key": summarized["issue_key"],
                    "action": summarized["summary"],
                    "rationale": summarized["rationale"],
                }
            )

    return {
        "mini_id": prediction.get("mini_id"),
        "reviewer_username": prediction.get("reviewer_username"),
        "guidance_available": True,
        "mode": "review_prediction",
        "unavailable_reason": None,
        "approval_state": prediction.get("approval_state"),
        "summary": prediction.get("summary"),
        "change_plan": change_plan,
        "questions_to_answer": prediction.get("open_questions", []),
        "delivery_policy": prediction.get("delivery_policy", {}),
        "prediction": raw_prediction,
    }


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

    When the mini has no framework profile yet the response is explicitly gated:
    ``frameworks_available=false``, ``mode="gated"``, and an ``unavailable_reason``.

    Args:
        username: GitHub username or mini UUID.
        min_confidence: Exclude frameworks below this threshold (0.0–1.0).
        limit: Maximum number of frameworks to return (default 20).
    """

    path = f"/minis/by-username/{quote(username, safe='')}/decision-frameworks"
    result = await _request_json(
        "GET",
        f"{path}?min_confidence={min_confidence}&limit={limit}",
    )
    if not isinstance(result, dict):
        raise BackendError("Expected a decision-framework payload from the backend.")

    frameworks = result.get("frameworks") if isinstance(result.get("frameworks"), list) else []
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}

    if not frameworks:
        return {
            "username": result.get("username", username),
            "frameworks_available": False,
            "mode": "gated",
            "unavailable_reason": "mini has no decision-framework evidence yet",
            "frameworks": [],
            "summary": {
                "total": int(summary.get("total", 0) or 0),
                "mean_confidence": float(summary.get("mean_confidence", 0.0) or 0.0),
                "max_revision": int(summary.get("max_revision", 0) or 0),
            },
        }

    return {
        "username": result.get("username", username),
        "frameworks_available": True,
        "mode": "frameworks",
        "unavailable_reason": None,
        "frameworks": frameworks,
        "summary": summary,
    }


async def _run_auth_login() -> None:
    config = await _github_device_config()
    device = await _request_github_device_code(config["client_id"], config["scope"])
    print("Authorize Minis MCP with GitHub:")
    print(f"  1. Open {device['verification_uri']}")
    print(f"  2. Enter code: {device['user_code']}")
    print("Waiting for authorization...")

    github_token = await _poll_github_device_token(
        client_id=config["client_id"],
        device_code=str(device["device_code"]),
        expires_in=int(device["expires_in"]),
        interval=int(device["interval"]),
    )
    minis_token = await _exchange_github_token_for_minis_token(github_token)
    token_path = _write_auth_token(str(minis_token["access_token"]))
    print(f"Authenticated as {minis_token.get('github_username')}.")
    print(f"Token saved to {token_path}.")
    print("Claude Code can now run this MCP server without MINIS_AUTH_TOKEN.")


def _run_auth_status() -> None:
    token = _auth_token()
    if not token:
        print("No Minis auth token found. Run: uv run minis-mcp auth login")
        raise SystemExit(1)
    source = "MINIS_AUTH_TOKEN" if os.environ.get("MINIS_AUTH_TOKEN") else str(_token_path())
    print(f"Minis auth token found via {source}.")


def main() -> None:
    if sys.argv[1:3] == ["auth", "login"]:
        asyncio.run(_run_auth_login())
        return
    if sys.argv[1:3] == ["auth", "status"]:
        _run_auth_status()
        return
    mcp.run()


if __name__ == "__main__":
    main()
