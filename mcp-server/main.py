"""Minis MCP Server -- Chat with AI personality clones of GitHub developers.

Thin wrapper around the Minis FastAPI backend (http://localhost:8000).
"""

from __future__ import annotations

import json
import os

import httpx
from fastmcp import FastMCP

BACKEND_URL = os.environ.get("MINIS_BACKEND_URL", "http://localhost:8000")
AUTH_TOKEN = os.environ.get("MINIS_AUTH_TOKEN", "")

mcp = FastMCP(
    "minis",
    instructions="Chat with AI personality clones of GitHub developers",
)


def _api(path: str) -> str:
    return f"{BACKEND_URL}/api{path}"


def _mini_path(identifier: str) -> str:
    """Return the API path for a mini, using id if numeric or by-username otherwise."""
    try:
        int(identifier)
        return f"/minis/{identifier}"
    except ValueError:
        return f"/minis/by-username/{identifier}"


async def _request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    timeout: float = 120.0,
    auth: bool = False,
) -> dict | list | str:
    """Make an HTTP request to the Minis backend and return parsed JSON."""
    headers: dict[str, str] = {}
    if auth and AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(method, _api(path), json=json_body, headers=headers)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return {"error": True, "status_code": resp.status_code, "detail": detail}
        content_type = resp.headers.get("content-type", "")
        if "text/" in content_type:
            return resp.text
        return resp.json()


@mcp.tool()
async def create_mini(username: str) -> str:
    """Create an AI personality clone from a GitHub username.

    Kicks off the ingestion pipeline that fetches the user's GitHub activity,
    extracts their engineering values and communication style, and builds a
    system prompt so you can chat with their AI clone.

    Returns the mini summary including its current status.
    """
    result = await _request("POST", "/minis", json_body={"username": username})
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def list_minis() -> str:
    """List all available minis (AI personality clones).

    Returns a JSON array of mini summaries with username, display name,
    status, and creation time.
    """
    result = await _request("GET", "/minis")
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_mini(identifier: str) -> str:
    """Get full details about a specific mini.

    Returns the mini's spirit document, extracted engineering values,
    personality patterns, communication style, and system prompt.

    Args:
        identifier: Mini's integer ID or GitHub username.
    """
    result = await _request("GET", _mini_path(identifier))
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_mini_status(identifier: str) -> str:
    """Check the pipeline creation status for a mini.

    Connects to the SSE status stream and collects all progress events
    until the pipeline completes or times out. Use this after create_mini
    to monitor progress.

    Args:
        identifier: Mini's integer ID or GitHub username.
    """
    events: list[dict] = []
    event_type = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=300.0)) as client:
            async with client.stream("GET", _api(f"{_mini_path(identifier)}/status")) as resp:
                if resp.status_code >= 400:
                    return json.dumps(
                        {"error": True, "status_code": resp.status_code}
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if event_type == "progress":
                            try:
                                events.append(json.loads(data))
                            except json.JSONDecodeError:
                                events.append({"raw": data})
                        elif event_type == "done":
                            events.append({"event": "done", "message": data})
                            break
                        elif event_type == "timeout":
                            events.append({"event": "timeout", "message": data})
                            break
    except httpx.ReadTimeout:
        events.append({"event": "timeout", "message": "Connection timed out"})
    except httpx.ConnectError:
        return json.dumps({"error": True, "detail": "Cannot connect to Minis backend"})

    return json.dumps(events, indent=2, default=str)


@mcp.tool()
async def chat_with_mini(identifier: str, message: str) -> str:
    """Send a message to a developer's AI personality clone and get a response.

    The mini will respond in the style and personality of the GitHub developer.
    Each call is a single-turn exchange; conversation history is not maintained
    between calls.

    Args:
        identifier: Mini's integer ID or GitHub username.
        message: Your message to the mini.
    """
    chunks: list[str] = []
    event_type = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=120.0)) as client:
            async with client.stream(
                "POST",
                _api(f"{_mini_path(identifier)}/chat"),
                json={"message": message, "history": []},
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    detail = body.decode()
                    try:
                        detail = json.loads(detail).get("detail", detail)
                    except Exception:
                        pass
                    return json.dumps(
                        {"error": True, "status_code": resp.status_code, "detail": detail}
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:") and event_type == "chunk":
                        chunks.append(line[len("data:"):].strip())
    except httpx.ConnectError:
        return json.dumps({"error": True, "detail": "Cannot connect to Minis backend"})

    return "".join(chunks)


@mcp.tool()
async def list_teams() -> str:
    """List all teams the user has access to.

    Returns a JSON array of team summaries with name, description,
    member count, and creation time.
    """
    result = await _request("GET", "/teams", auth=True)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_team(team_id: int) -> str:
    """Get team details including members.

    Args:
        team_id: The team's integer ID.
    """
    result = await _request("GET", f"/teams/{team_id}")
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def team_chat(team_id: int, message: str, context: str = "") -> str:
    """Send a message to all minis on a team and get their responses.

    Each team member will respond from their unique perspective.
    Collects all member responses and returns them together.

    Args:
        team_id: The team's integer ID.
        message: Your message to the team.
        context: Optional additional context for the conversation.
    """
    responses: dict[str, str] = {}
    current_member = ""
    current_chunks: list[str] = []
    event_type = ""

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=300.0)) as client:
            async with client.stream(
                "POST",
                _api(f"/teams/{team_id}/chat"),
                json={"message": message, "context": context or None},
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    detail = body.decode()
                    try:
                        detail = json.loads(detail).get("detail", detail)
                    except Exception:
                        pass
                    return json.dumps(
                        {"error": True, "status_code": resp.status_code, "detail": detail}
                    )
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if event_type == "member_start":
                            try:
                                info = json.loads(data)
                                current_member = info.get("display_name") or info.get("username", "unknown")
                                current_chunks = []
                            except json.JSONDecodeError:
                                pass
                        elif event_type == "member_chunk":
                            try:
                                chunk_data = json.loads(data)
                                current_chunks.append(chunk_data.get("chunk", ""))
                            except json.JSONDecodeError:
                                pass
                        elif event_type == "member_done":
                            if current_member:
                                responses[current_member] = "".join(current_chunks)
                        elif event_type == "done":
                            break
    except httpx.ConnectError:
        return json.dumps({"error": True, "detail": "Cannot connect to Minis backend"})

    # Format as readable output
    parts = []
    for name, response in responses.items():
        parts.append(f"## {name}\n\n{response}")
    return "\n\n---\n\n".join(parts) if parts else "No responses received."


@mcp.tool()
async def get_mini_soul_doc(identifier: str) -> str:
    """Get the raw soul document for a mini -- their distilled personality.

    Returns the spirit/soul document as plain text markdown.

    Args:
        identifier: Mini's integer ID or GitHub username.
    """
    path = _mini_path(identifier)
    result = await _request("GET", f"/export{path}/soul-doc")
    if isinstance(result, dict) and result.get("error"):
        return json.dumps(result, indent=2)
    return str(result)


@mcp.tool()
async def get_mini_memory(identifier: str, query: str = "") -> str:
    """Get a mini's memory bank, optionally filtered by query.

    The memory bank contains factual knowledge extracted during
    personality synthesis. Use query to search for specific topics.

    Args:
        identifier: Mini's integer ID or GitHub username.
        query: Optional search term to filter memory entries.
    """
    result = await _request("GET", _mini_path(identifier))
    if isinstance(result, dict) and result.get("error"):
        return json.dumps(result, indent=2)

    mini = result if isinstance(result, dict) else {}
    memory = mini.get("memory_content", "")
    if not memory:
        return "No memory content available for this mini."

    if query:
        lines = memory.split("\n")
        matches = [line for line in lines if query.lower() in line.lower()]
        if not matches:
            return f"No memory entries matching '{query}'."
        return "\n".join(matches[:20])

    return memory


@mcp.tool()
async def export_subagent(identifier: str, format: str = "claude_code") -> str:
    """Export a mini as a Claude Code agent definition (.md file).

    Drop the output into .claude/agents/ to use as a subagent.

    Args:
        identifier: Mini's integer ID or GitHub username.
        format: Export format (currently only "claude_code").
    """
    path = _mini_path(identifier)
    result = await _request("GET", f"/export{path}/subagent?format={format}")
    if isinstance(result, dict) and result.get("error"):
        return json.dumps(result, indent=2)
    return str(result)


@mcp.tool()
async def export_team_agents(team_id: int, format: str = "claude_code") -> str:
    """Export all minis in a team as Claude Code agent definitions.

    Returns the agent .md files and a team config YAML.

    Args:
        team_id: The team's integer ID.
        format: Export format (currently only "claude_code").
    """
    result = await _request("GET", f"/export/teams/{team_id}/agent-team?format={format}")
    if isinstance(result, dict) and result.get("error"):
        return json.dumps(result, indent=2)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def compare_minis(mini_ids: list[int], topic: str) -> str:
    """Compare multiple minis' perspectives on a topic.

    Sends the same question to each mini and collects their responses
    side by side for comparison.

    Args:
        mini_ids: List of mini IDs to compare.
        topic: The topic or question to ask each mini about.
    """
    responses: dict[int, str] = {}
    for mid in mini_ids:
        resp = await chat_with_mini(str(mid), f"What's your take on: {topic}")
        responses[mid] = resp

    # Format as readable comparison
    parts = []
    for mid, response in responses.items():
        parts.append(f"## Mini #{mid}\n\n{response}")
    return "\n\n---\n\n".join(parts)


if __name__ == "__main__":
    mcp.run()
