from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


def test_decision_frameworks_displays_table_with_frameworks(monkeypatch):
    """Test that decision-frameworks displays a table with frameworks sorted by confidence."""

    async def fake_execute(*args, **kwargs):
        # Mock Mini object
        mini = MagicMock()
        mini.username = "alice"
        mini.principles_json = {
            "decision_frameworks": {
                "frameworks": [
                    {
                        "framework_id": "fw-001",
                        "confidence": 0.95,
                        "revision": 2,
                        "trigger": "Someone submits a PR with minimal tests",
                        "action": "Request comprehensive coverage before approval",
                        "value": "Quality over speed",
                    },
                    {
                        "framework_id": "fw-002",
                        "confidence": 0.78,
                        "revision": 1,
                        "trigger": "Team member asks for architectural advice",
                        "action": "Suggest modular design patterns",
                        "value": "Maintainability",
                    },
                    {
                        "framework_id": "fw-003",
                        "confidence": 0.85,
                        "revision": 3,
                        "trigger": "Code review on legacy system",
                        "action": "Suggest gradual refactoring",
                        "value": "Pragmatism",
                    },
                ]
            }
        }
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "alice"])

    assert result.exit_code == 0
    assert "Decision Frameworks: alice" in result.output
    assert "fw-001" in result.output
    assert "fw-002" in result.output
    assert "fw-003" in result.output
    # Check that value fields appear (may be truncated due to table wrapping)
    assert "Quality over" in result.output
    assert "Maintainabi" in result.output
    assert "Pragmatism" in result.output
    # Verify sorting by confidence desc: 0.95 should come before 0.78
    assert result.output.find("0.95") < result.output.find("0.78")
    # Verify summary
    assert "3 frameworks" in result.output
    assert "max revision 3" in result.output


def test_decision_frameworks_respects_limit(monkeypatch):
    """Test that --limit flag restricts output."""

    async def fake_execute(*args, **kwargs):
        mini = MagicMock()
        mini.username = "bob"
        mini.principles_json = {
            "decision_frameworks": {
                "frameworks": [
                    {
                        "framework_id": f"fw-{i:03d}",
                        "confidence": 0.9 - (i * 0.05),
                        "revision": i,
                        "trigger": f"trigger {i}",
                        "action": f"action {i}",
                        "value": f"value {i}",
                    }
                    for i in range(10)
                ]
            }
        }
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "bob", "--limit", "3"])

    assert result.exit_code == 0
    # Should show 3 frameworks, not 10
    assert "3 frameworks" in result.output
    assert "fw-000" in result.output
    assert "fw-001" in result.output
    assert "fw-002" in result.output
    assert "fw-009" not in result.output


def test_decision_frameworks_respects_min_confidence(monkeypatch):
    """Test that --min-confidence flag filters frameworks."""

    async def fake_execute(*args, **kwargs):
        mini = MagicMock()
        mini.username = "charlie"
        mini.principles_json = {
            "decision_frameworks": {
                "frameworks": [
                    {
                        "framework_id": "fw-high",
                        "confidence": 0.9,
                        "revision": 1,
                        "trigger": "trigger high",
                        "action": "action high",
                        "value": "value high",
                    },
                    {
                        "framework_id": "fw-low",
                        "confidence": 0.5,
                        "revision": 1,
                        "trigger": "trigger low",
                        "action": "action low",
                        "value": "value low",
                    },
                ]
            }
        }
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(
        minis_cli.app, ["decision-frameworks", "charlie", "--min-confidence", "0.7"]
    )

    assert result.exit_code == 0
    # Should only show the high-confidence one
    assert "fw-high" in result.output
    assert "fw-low" not in result.output
    assert "1 frameworks" in result.output


def test_decision_frameworks_handles_empty_profile(monkeypatch):
    """Test that empty framework profile shows helpful message."""

    async def fake_execute(*args, **kwargs):
        mini = MagicMock()
        mini.username = "dave"
        mini.principles_json = {}
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "dave"])

    assert result.exit_code == 0
    assert "No decision frameworks found" in result.output


def test_decision_frameworks_handles_missing_mini(monkeypatch):
    """Test that missing mini shows error."""

    async def fake_execute(*args, **kwargs):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "nonexistent"])

    assert result.exit_code == 1
    assert "Mini 'nonexistent' not found" in result.output


def test_decision_frameworks_handles_none_principles_json(monkeypatch):
    """Test that None principles_json shows helpful message."""

    async def fake_execute(*args, **kwargs):
        mini = MagicMock()
        mini.username = "eve"
        mini.principles_json = None
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "eve"])

    assert result.exit_code == 0
    assert "No decision frameworks found" in result.output


def test_decision_frameworks_truncates_long_fields(monkeypatch):
    """Test that long trigger/action/value fields are truncated."""

    async def fake_execute(*args, **kwargs):
        mini = MagicMock()
        mini.username = "frank"
        mini.principles_json = {
            "decision_frameworks": {
                "frameworks": [
                    {
                        "framework_id": "fw-long",
                        "confidence": 0.88,
                        "revision": 1,
                        "trigger": "A" * 100,
                        "action": "B" * 100,
                        "value": "C" * 100,
                    }
                ]
            }
        }
        return MagicMock(scalar_one_or_none=MagicMock(return_value=mini))

    mock_session = MagicMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    def mock_async_session(*args, **kwargs):
        return mock_session

    monkeypatch.setattr(minis_cli, "async_session", mock_async_session)

    result = runner.invoke(minis_cli.app, ["decision-frameworks", "frank"])

    assert result.exit_code == 0
    # Should contain truncated versions
    assert "A" * 60 not in result.output  # trigger truncates to 60
    assert "B" * 60 not in result.output  # action truncates to 60
    assert "C" * 40 not in result.output  # value truncates to 40
