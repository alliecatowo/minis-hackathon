"""Tests for ALLIE-405: rate limits, cost caps, LLM kill switch, observability."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(github_username: str | None = None, display_name: str | None = None):
    return SimpleNamespace(github_username=github_username, display_name=display_name)


@pytest_asyncio.fixture
async def rate_limit_store():
    """SQLite-backed persistent limiter for tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.core.persistent_rate_limit import DatabaseSlidingWindowRateLimitStore
    from app.models.rate_limit import SlidingRateLimitEvent

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SlidingRateLimitEvent.__table__.create)

    yield DatabaseSlidingWindowRateLimitStore(
        async_sessionmaker(engine, expire_on_commit=False)
    )

    await engine.dispose()


# ---------------------------------------------------------------------------
# 1. LLM kill switch tests
# ---------------------------------------------------------------------------


class TestLLMKillSwitch:
    def test_kill_switch_raises_when_disabled(self):
        """_check_llm_kill_switch raises LLMDisabledError when flag is set."""
        from app.core.agent import LLMDisabledError, _check_llm_kill_switch

        mock_settings = MagicMock()
        mock_settings.llm_disabled = True
        mock_settings.disable_llm_calls = "true"

        with patch("app.core.agent.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with pytest.raises(LLMDisabledError):
                    _check_llm_kill_switch(caller="test")

    def test_kill_switch_passes_when_enabled(self):
        """_check_llm_kill_switch does nothing when flag is not set."""
        from app.core.agent import _check_llm_kill_switch

        mock_settings = MagicMock()
        mock_settings.llm_disabled = False
        mock_settings.disable_llm_calls = ""

        with patch("app.core.config.settings", mock_settings):
            _check_llm_kill_switch(caller="test")  # should not raise

    @pytest.mark.asyncio
    async def test_run_agent_raises_503_style_error_on_kill_switch(self):
        """run_agent propagates LLMDisabledError when kill switch is active."""
        from app.core.agent import LLMDisabledError, run_agent, AgentTool

        mock_settings = MagicMock()
        mock_settings.llm_disabled = True
        mock_settings.disable_llm_calls = "1"

        async def noop(**kwargs):
            return "ok"

        tools = [AgentTool(name="t", description="d", parameters={}, handler=noop)]

        with patch("app.core.config.settings", mock_settings):
            with pytest.raises(LLMDisabledError):
                await run_agent(
                    system_prompt="sys",
                    user_prompt="hi",
                    tools=tools,
                )

    @pytest.mark.asyncio
    async def test_run_agent_streaming_raises_on_kill_switch(self):
        """run_agent_streaming propagates LLMDisabledError when kill switch is active."""
        from app.core.agent import LLMDisabledError, run_agent_streaming, AgentTool

        mock_settings = MagicMock()
        mock_settings.llm_disabled = True
        mock_settings.disable_llm_calls = "true"

        async def noop(**kwargs):
            return "ok"

        tools = [AgentTool(name="t", description="d", parameters={}, handler=noop)]

        with patch("app.core.config.settings", mock_settings):
            with pytest.raises(LLMDisabledError):
                async for _ in run_agent_streaming(
                    system_prompt="sys",
                    user_prompt="hi",
                    tools=tools,
                ):
                    pass

    def test_settings_llm_disabled_property_truthy_values(self):
        """Settings.llm_disabled is True for 'true', '1', 'yes'."""
        from app.core.config import Settings

        for val in ("true", "True", "TRUE", "1", "yes", "Yes"):
            s = Settings(disable_llm_calls=val)
            assert s.llm_disabled is True, f"Expected True for {val!r}"

    def test_settings_llm_disabled_property_falsy_values(self):
        """Settings.llm_disabled is False for empty string and unset."""
        from app.core.config import Settings

        for val in ("", "false", "0", "no"):
            s = Settings(disable_llm_calls=val)
            assert s.llm_disabled is False, f"Expected False for {val!r}"


class TestLLMUsageLimits:
    @pytest.mark.asyncio
    async def test_run_agent_applies_explicit_token_caps(self):
        """run_agent forwards per-call token caps to PydanticAI UsageLimits."""
        from app.core import agent as agent_module
        from app.core.agent import run_agent

        mock_result = MagicMock()
        mock_result.output = "ok"
        mock_result.usage.return_value = SimpleNamespace(
            requests=1,
            request_tokens=10,
            response_tokens=5,
        )
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_agent_class = MagicMock(return_value=mock_agent)

        with patch.object(agent_module, "Agent", mock_agent_class):
            await run_agent(
                system_prompt="Return ok.",
                user_prompt="ok",
                tools=[],
                max_turns=2,
                max_input_tokens=123,
                max_output_tokens=45,
                max_total_tokens=160,
            )

        _, kwargs = mock_agent.run.call_args
        limits = kwargs["usage_limits"]
        assert limits.request_limit == 2
        assert limits.input_tokens_limit == 123
        assert limits.output_tokens_limit == 45
        assert limits.total_tokens_limit == 160

    @pytest.mark.asyncio
    async def test_run_agent_applies_env_token_caps(self, monkeypatch):
        """Env caps let CI bound live LLM tests without changing call sites."""
        from app.core import agent as agent_module
        from app.core.agent import run_agent

        monkeypatch.setenv("LLM_REQUEST_TOKEN_LIMIT", "100")
        monkeypatch.setenv("LLM_RESPONSE_TOKEN_LIMIT", "50")
        monkeypatch.setenv("LLM_TOTAL_TOKEN_LIMIT", "125")

        mock_result = MagicMock()
        mock_result.output = "ok"
        mock_result.usage.return_value = SimpleNamespace(
            requests=1,
            request_tokens=10,
            response_tokens=5,
        )
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_agent_class = MagicMock(return_value=mock_agent)

        with patch.object(agent_module, "Agent", mock_agent_class):
            await run_agent(system_prompt="Return ok.", user_prompt="ok", tools=[])

        _, kwargs = mock_agent.run.call_args
        limits = kwargs["usage_limits"]
        assert limits.input_tokens_limit == 100
        assert limits.output_tokens_limit == 50
        assert limits.total_tokens_limit == 125


# ---------------------------------------------------------------------------
# 2. Per-IP + per-mini chat throttle tests
# ---------------------------------------------------------------------------


class TestChatIpMiniThrottle:
    """Tests for check_chat_ip_mini_limit()."""

    @pytest.mark.asyncio
    async def test_allows_first_request(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_chat_ip_mini_limit

        mock_settings = MagicMock()
        mock_settings.chat_ip_mini_hourly_limit = 20
        mock_settings.chat_ip_mini_burst_limit = 5

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                # Should not raise
                await check_chat_ip_mini_limit(
                    "1.2.3.4", "mini-abc", user=None, store=rate_limit_store
                )

    @pytest.mark.asyncio
    async def test_burst_limit_exceeded_returns_429(self, rate_limit_store):
        """Sending more than burst_limit requests in one minute raises 429."""
        from app.middleware.ip_rate_limit import check_chat_ip_mini_limit

        mock_settings = MagicMock()
        mock_settings.chat_ip_mini_hourly_limit = 100  # high hourly so it doesn't trip
        mock_settings.chat_ip_mini_burst_limit = 3

        # Non-admin user
        non_admin = _make_user(github_username="randomdev")
        admin_list = ["alliecatowo"]

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.admin.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # First 3 should pass
                    for _ in range(3):
                        await check_chat_ip_mini_limit(
                            "9.8.7.6", "mini-xyz", user=non_admin, store=rate_limit_store
                        )

                    # 4th should be blocked
                    with pytest.raises(HTTPException) as exc_info:
                        await check_chat_ip_mini_limit(
                            "9.8.7.6", "mini-xyz", user=non_admin, store=rate_limit_store
                        )
                    assert exc_info.value.status_code == 429
                    assert "Retry-After" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_hourly_limit_exceeded_returns_429(self, rate_limit_store):
        """Exceeding the hourly limit raises 429."""
        from app.middleware.ip_rate_limit import check_chat_ip_mini_limit

        mock_settings = MagicMock()
        mock_settings.chat_ip_mini_hourly_limit = 5
        mock_settings.chat_ip_mini_burst_limit = 100  # high burst so it doesn't trip

        non_admin = _make_user(github_username="randomdev")
        admin_list = ["alliecatowo"]

        # Pre-fill the hourly window to the limit to avoid the burst window interfering
        ip = "5.6.7.8"
        mini_id = "mini-hourly-test"

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.admin.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    for _ in range(5):
                        await check_chat_ip_mini_limit(
                            ip, mini_id, user=non_admin, store=rate_limit_store
                        )
                    with pytest.raises(HTTPException) as exc_info:
                        await check_chat_ip_mini_limit(
                            ip, mini_id, user=non_admin, store=rate_limit_store
                        )
                    assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_admin_user_bypasses_throttle(self, rate_limit_store):
        """Admin users bypass the per-IP + per-mini chat throttle."""
        from app.middleware.ip_rate_limit import check_chat_ip_mini_limit

        mock_settings = MagicMock()
        mock_settings.chat_ip_mini_hourly_limit = 1  # very low limit
        mock_settings.chat_ip_mini_burst_limit = 1

        admin = _make_user(github_username="alliecatowo")
        admin_list = ["alliecatowo"]

        # Pre-fill windows to exceed both limits
        ip = "3.3.3.3"
        mini_id = "mini-admin-test"

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.admin.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # Should NOT raise — admin bypass
                    await check_chat_ip_mini_limit(
                        ip, mini_id, user=admin, store=rate_limit_store
                    )

    @pytest.mark.asyncio
    async def test_rapid_calls_eventually_429(self, rate_limit_store):
        """Simulating 30+ rapid calls returns 429 at burst limit."""
        from app.middleware.ip_rate_limit import check_chat_ip_mini_limit

        mock_settings = MagicMock()
        mock_settings.chat_ip_mini_hourly_limit = 1000
        mock_settings.chat_ip_mini_burst_limit = 5

        non_admin = _make_user(github_username="rapidfire")
        admin_list = ["alliecatowo"]

        blocked = 0
        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.admin.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    for _ in range(30):
                        try:
                            await check_chat_ip_mini_limit(
                                "7.7.7.7",
                                "mini-rapid",
                                user=non_admin,
                                store=rate_limit_store,
                            )
                        except HTTPException as e:
                            if e.status_code == 429:
                                blocked += 1

        assert blocked > 0, "Expected at least one 429 in 30 rapid calls"


# ---------------------------------------------------------------------------
# 3. Pipeline token cost cap tests
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_hard_cap_not_exceeded(self):
        """Records within budget don't raise."""
        from app.synthesis.pipeline import TokenBudget

        budget = TokenBudget(hard_cap=1_000_000, soft_cap=500_000, mini_id="test-mini")
        budget.record(100_000, 50_000, source="github")
        assert budget.total_tokens == 150_000

    def test_hard_cap_exceeded_raises(self):
        """Recording tokens over the hard cap raises TokenBudgetExceeded."""
        from app.synthesis.pipeline import TokenBudget, TokenBudgetExceeded

        budget = TokenBudget(hard_cap=100_000, soft_cap=50_000, mini_id="test-mini")
        budget.record(90_000, 5_000, source="github")  # 95k — under cap

        with pytest.raises(TokenBudgetExceeded):
            budget.record(10_000, 0, source="blog")  # pushes over 100k

    def test_soft_cap_check_returns_true_when_exceeded(self):
        """check_soft_cap returns True after soft cap is crossed."""
        from app.synthesis.pipeline import TokenBudget

        budget = TokenBudget(hard_cap=2_000_000, soft_cap=500_000, mini_id="test-mini")
        budget.record(400_000, 150_000, source="github")  # 550k — over soft cap
        assert budget.check_soft_cap(source="github") is True

    def test_soft_cap_check_returns_false_when_under(self):
        """check_soft_cap returns False when still under the soft cap."""
        from app.synthesis.pipeline import TokenBudget

        budget = TokenBudget(hard_cap=2_000_000, soft_cap=500_000, mini_id="test-mini")
        budget.record(100_000, 50_000, source="github")
        assert budget.check_soft_cap(source="github") is False

    def test_cumulative_tracking_across_multiple_records(self):
        """total_tokens accumulates correctly across multiple record() calls."""
        from app.synthesis.pipeline import TokenBudget

        budget = TokenBudget(hard_cap=10_000_000, soft_cap=5_000_000, mini_id="test-mini")
        budget.record(100_000, 50_000, source="github")
        budget.record(200_000, 100_000, source="blog")
        budget.record(50_000, 25_000, source="hackernews")
        assert budget.total_tokens == 525_000

    def test_default_config_values_are_reasonable(self):
        """Default MAX_PIPELINE_TOKENS_PER_MINI and MAX_AGENT_TOKENS are sane."""
        from app.core.config import Settings

        s = Settings()
        assert s.max_pipeline_tokens_per_mini == 2_000_000
        assert s.max_agent_tokens == 500_000


# ---------------------------------------------------------------------------
# 4. LLM usage observability tests
# ---------------------------------------------------------------------------


class TestLLMUsageObservability:
    def test_log_llm_call_emits_structured_log(self, caplog):
        """log_llm_call emits a structured log line with all fields."""
        import logging

        from app.core.llm_usage import log_llm_call

        with caplog.at_level(logging.INFO, logger="app.core.llm_usage"):
            log_llm_call(
                tier="STANDARD",
                tokens_in=1000,
                tokens_out=500,
                user_id="user-123",
                mini_id="mini-456",
                endpoint="/api/minis/chat",
                model="google-gla:gemini-2.5-flash",
            )

        assert any("llm.usage" in r.message for r in caplog.records)
        record = next(r for r in caplog.records if "llm.usage" in r.message)
        assert "STANDARD" in record.message
        assert "1000" in record.message
        assert "500" in record.message

    def test_log_llm_call_anonymous_user(self, caplog):
        """log_llm_call uses 'anonymous' when user_id is None."""
        import logging

        from app.core.llm_usage import log_llm_call

        with caplog.at_level(logging.INFO, logger="app.core.llm_usage"):
            log_llm_call(
                tier="FAST",
                tokens_in=100,
                tokens_out=50,
                user_id=None,
            )

        record = next(r for r in caplog.records if "llm.usage" in r.message)
        assert "anonymous" in record.message

    @pytest.mark.asyncio
    async def test_record_llm_call_async_noop_without_session_factory(self):
        """record_llm_call_async is a no-op when session_factory is None."""
        from app.core.llm_usage import record_llm_call_async

        # Should not raise
        await record_llm_call_async(
            tier="STANDARD",
            tokens_in=1000,
            tokens_out=500,
            session_factory=None,
        )

    @pytest.mark.asyncio
    async def test_get_last_24h_totals_noop_on_exception(self):
        """get_last_24h_totals returns [] when DB call fails."""
        from app.core.llm_usage import get_last_24h_totals

        async def bad_session():
            raise RuntimeError("DB down")

        result = await get_last_24h_totals(bad_session)
        assert result == []
