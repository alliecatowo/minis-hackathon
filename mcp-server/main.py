"""Minis MCP Server -- Chat with AI personality clones of GitHub developers.

Thin wrapper around the Minis FastAPI backend (http://localhost:8000).
"""

from __future__ import annotations

import json
import os

import httpx
from fastmcp import FastMCP

BACKEND_URL = os.environ.get("MINIS_BACKEND_URL", "http://localhost:8000")

mcp = FastMCP(
    "minis",
    instructions="Chat with AI personality clones of GitHub developers",
)


def _api(path: str) -> str:
    return f"{BACKEND_URL}/api{path}"


async def _request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    timeout: float = 120.0,
) -> dict | list:
    """Make an HTTP request to the Minis backend and return parsed JSON."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(method, _api(path), json=json_body)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return {"error": True, "status_code": resp.status_code, "detail": detail}
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
async def get_mini(username: str) -> str:
    """Get full details about a specific mini.

    Returns the mini's spirit document, extracted engineering values,
    personality patterns, communication style, and system prompt.
    """
    result = await _request("GET", f"/minis/{username}")
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
async def get_mini_status(username: str) -> str:
    """Check the pipeline creation status for a mini.

    Connects to the SSE status stream and collects all progress events
    until the pipeline completes or times out. Use this after create_mini
    to monitor progress.
    """
    events: list[dict] = []
    event_type = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=300.0)) as client:
            async with client.stream("GET", _api(f"/minis/{username}/status")) as resp:
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
async def chat_with_mini(username: str, message: str) -> str:
    """Send a message to a developer's AI personality clone and get a response.

    The mini will respond in the style and personality of the GitHub developer.
    Each call is a single-turn exchange; conversation history is not maintained
    between calls.

    Args:
        username: GitHub username of the mini to chat with.
        message: Your message to the mini.
    """
    chunks: list[str] = []
    event_type = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=120.0)) as client:
            async with client.stream(
                "POST",
                _api(f"/minis/{username}/chat"),
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


if __name__ == "__main__":
    mcp.run()
