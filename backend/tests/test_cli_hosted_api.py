from __future__ import annotations

from typing import Any

import httpx
from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


def _response(
    method: str,
    url: str,
    *,
    status_code: int = 200,
    json: object | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=json,
    )


class _FakeStream:
    def __init__(self, lines: list[str], *, status_code: int = 200):
        self._lines = lines
        self._response = httpx.Response(
            status_code,
            request=httpx.Request("POST", "https://api.test/api/minis/mini-1/chat"),
            text="error",
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_lines(self):
        yield from self._lines


def test_create_requires_auth_before_calling_api(monkeypatch):
    monkeypatch.delenv("MINIS_TOKEN", raising=False)
    monkeypatch.delenv("MINIS_AUTH_TOKEN", raising=False)

    def unexpected_post(*args, **kwargs):
        raise AssertionError("API should not be called without auth")

    monkeypatch.setattr(minis_cli.httpx, "post", unexpected_post)

    result = runner.invoke(minis_cli.app, ["create", "octocat"])

    assert result.exit_code == 1
    assert "Authentication required" in result.output
    assert "MINIS_TOKEN" in result.output


def test_list_happy_path_uses_hosted_api(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _response(
            "GET",
            url,
            json={
                "data": [
                    {
                        "id": "mini-1",
                        "username": "octocat",
                        "display_name": "Octo Cat",
                        "status": "ready",
                        "created_at": "2026-04-25T12:00:00Z",
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            },
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)

    result = runner.invoke(minis_cli.app, ["list"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.test/api/minis?mine=false"
    assert captured["headers"] == {"Accept": "application/json"}
    assert "octocat" in result.output
    assert "ready" in result.output


def test_create_happy_path_sends_bearer_token(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    monkeypatch.setenv("MINIS_TOKEN", "secret-token")
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _response(
            "POST",
            url,
            status_code=202,
            json={"id": "mini-1", "username": "octocat", "status": "processing"},
        )

    monkeypatch.setattr(minis_cli.httpx, "post", fake_post)

    result = runner.invoke(minis_cli.app, ["create", "octocat"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.test/api/minis"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"] == {"username": "octocat", "sources": ["github"]}
    assert "create accepted" in result.output
    assert "processing" in result.output


def test_chat_one_shot_collects_sse_chunks(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={
                "id": "mini-1",
                "username": "octocat",
                "display_name": "Octo Cat",
                "status": "ready",
            },
        )

    def fake_stream(method: str, url: str, **kwargs) -> _FakeStream:
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeStream(
            [
                "event: conversation_id",
                "data: conv-1",
                "",
                "event: chunk",
                "data: Hello ",
                "",
                "event: chunk",
                "data: world",
                "",
                "event: done",
                "data: ",
                "",
            ]
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", fake_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "What do you think?"])

    assert result.exit_code == 0, result.output
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.test/api/minis/mini-1/chat"
    assert captured["json"]["message"] == "What do you think?"
    assert captured["json"]["history"] == []
    assert "Hello world" in result.output


def test_chat_returns_explicit_gated_state_when_mini_processing(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={"id": "mini-1", "username": "octocat", "status": "processing"},
        )

    def unexpected_stream(*args, **kwargs):
        raise AssertionError("chat stream should not be opened when mini is gated")

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", unexpected_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "hi"])

    assert result.exit_code == 1
    assert "Chat unavailable" in result.output
    assert "gated until" in result.output
    assert "status=ready" in result.output


def test_chat_error_event_is_not_rendered_as_fake_output(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={"id": "mini-1", "username": "octocat", "status": "ready"},
        )

    def fake_stream(method: str, url: str, **kwargs) -> _FakeStream:
        return _FakeStream(
            [
                "event: error",
                "data: DISABLE_LLM_CALLS is enabled",
                "",
            ]
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", fake_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "hi"])

    assert result.exit_code == 1
    assert "Chat unavailable" in result.output
    assert "DISABLE_LLM_CALLS is enabled" in result.output
    assert "octocat:" in result.output
