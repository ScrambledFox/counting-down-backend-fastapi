"""Login brute-force protection and AI cost guards (Phase 3 gate), against the test database."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.integrations.openai_client import OpenAIClient
from app.models.mongo import AsyncDB
from app.repositories.usage_counters import UsageCounterRepository, ensure_usage_counter_indexes
from app.schemas.v1.user import UserType
from app.services import usage_limits
from app.services.auth import AuthService
from app.services.usage_limits import (
    AIUsageGuard,
    AIUsageLimitExceededError,
    LoginAttemptGuard,
    client_address,
)
from app.util.time import utc_now

settings = get_settings()


@pytest_asyncio.fixture
async def counters() -> AsyncGenerator[UsageCounterRepository]:
    db: AsyncDB = get_test_db()
    collection = db[settings.usage_counters_collection_name]
    await collection.delete_many({})
    await ensure_usage_counter_indexes(db)
    yield UsageCounterRepository(db)
    await collection.delete_many({})


@pytest.fixture
def limits(monkeypatch: pytest.MonkeyPatch):
    def apply(**values: int) -> None:
        for name, value in values.items():
            monkeypatch.setattr(usage_limits.settings, name, value)

    return apply


@pytest.mark.asyncio
async def test_concurrent_increments_share_one_counter(counters: UsageCounterRepository) -> None:
    results = await asyncio.gather(*(counters.increment("race", 60) for _ in range(25)))

    assert sorted(results) == list(range(1, 26))
    assert await counters.current("race", 60) == 25


@pytest.mark.asyncio
async def test_counters_start_again_in_the_next_window(counters: UsageCounterRepository) -> None:
    now = utc_now()
    await counters.increment("windowed", 60, now)
    await counters.increment("windowed", 60, now)

    assert await counters.current("windowed", 60, now) == 2
    assert await counters.current("windowed", 60, now + timedelta(seconds=60)) == 0
    assert await counters.increment("windowed", 60, now + timedelta(seconds=60)) == 1


@pytest.mark.asyncio
async def test_failed_logins_block_only_the_offending_client(
    counters: UsageCounterRepository, limits
) -> None:
    limits(login_max_failures_per_client=3, login_max_failures_global=100)
    guard = LoginAttemptGuard(counters)

    for _ in range(3):
        await guard.ensure_allowed("203.0.113.7")
        await guard.record_failure("203.0.113.7")

    with pytest.raises(HTTPException) as blocked:
        await guard.ensure_allowed("203.0.113.7")
    assert blocked.value.status_code == 429
    assert blocked.value.headers == {"Retry-After": str(settings.login_failure_window_seconds)}
    await guard.ensure_allowed("198.51.100.4")  # another address is unaffected


@pytest.mark.asyncio
async def test_failed_logins_from_many_addresses_pause_login(
    counters: UsageCounterRepository, limits
) -> None:
    limits(login_max_failures_per_client=10, login_max_failures_global=4)
    guard = LoginAttemptGuard(counters)

    for index in range(4):
        await guard.record_failure(f"192.0.2.{index}")

    with pytest.raises(HTTPException) as paused:
        await guard.ensure_allowed("192.0.2.200")
    assert paused.value.status_code == 429


@pytest.mark.asyncio
async def test_client_addresses_are_stored_only_as_hashes(
    counters: UsageCounterRepository,
) -> None:
    await LoginAttemptGuard(counters).record_failure("203.0.113.99")

    stored = await get_test_db()[settings.usage_counters_collection_name].find().to_list(None)
    assert stored
    assert all("203.0.113.99" not in document["_id"] for document in stored)


class _FakeSessions:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def delete_expired_sessions(self) -> None:
        return None

    async def get_session_by_access_key(self, _username: str) -> None:
        return None

    async def create_session(self, session: Any) -> Any:
        self.created.append(session)
        return session


@pytest.mark.asyncio
async def test_login_counts_failures_and_blocks_before_checking_the_key(
    counters: UsageCounterRepository, limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import auth as auth_module

    limits(login_max_failures_per_client=2, login_max_failures_global=100)
    monkeypatch.setattr(auth_module.settings, "access_key_joris", "synthetic-correct-key")
    sessions = _FakeSessions()
    users = SimpleNamespace(
        get_user_from_user_type=lambda user_type: SimpleNamespace(username=user_type)
    )
    service = AuthService(sessions, users, LoginAttemptGuard(counters))  # type: ignore[arg-type]

    for _ in range(2):
        with pytest.raises(HTTPException) as wrong:
            await service.login_user("synthetic-wrong-key", "203.0.113.8")
        assert wrong.value.status_code == 403

    # Even the correct key is refused while the address is blocked, so guesses reveal nothing.
    with pytest.raises(HTTPException) as blocked:
        await service.login_user("synthetic-correct-key", "203.0.113.8")
    assert blocked.value.status_code == 429
    assert sessions.created == []

    # The other user's device logs in normally.
    session = await service.login_user("synthetic-correct-key", "198.51.100.8")
    assert session.user_type == UserType.JORIS


@pytest.mark.asyncio
async def test_ai_budget_stops_generation_after_the_daily_limit(
    counters: UsageCounterRepository, limits
) -> None:
    limits(ai_daily_request_limit=2)
    guard = AIUsageGuard(counters)

    await guard.ensure_ai_available()
    await guard.consume_ai_request()
    await guard.consume_ai_request()
    with pytest.raises(AIUsageLimitExceededError):
        await guard.consume_ai_request()
    with pytest.raises(HTTPException) as refused:
        await guard.ensure_ai_available()
    assert refused.value.status_code == 429


@pytest.mark.asyncio
async def test_zero_disables_the_ai_limits(counters: UsageCounterRepository, limits) -> None:
    limits(ai_daily_request_limit=0, mediation_ai_daily_runs_per_user=0)
    guard = AIUsageGuard(counters)

    for _ in range(3):
        await guard.consume_ai_request()
        await guard.consume_mediation_run(UserType.JORIS)
    await guard.ensure_ai_available()
    assert await counters.current(usage_limits.AI_REQUESTS_SCOPE, usage_limits.DAY_SECONDS) == 0


@pytest.mark.asyncio
async def test_mediation_allowance_is_per_person(counters: UsageCounterRepository, limits) -> None:
    limits(mediation_ai_daily_runs_per_user=1)
    guard = AIUsageGuard(counters)

    await guard.consume_mediation_run(UserType.JORIS)
    with pytest.raises(HTTPException) as refused:
        await guard.consume_mediation_run(UserType.JORIS)
    assert refused.value.status_code == 429
    await guard.consume_mediation_run(UserType.DANFENG)


class _RecordingGuard:
    def __init__(self, *, exhausted: bool = False) -> None:
        self.calls = 0
        self.exhausted = exhausted

    async def consume_ai_request(self) -> None:
        self.calls += 1
        if self.exhausted:
            raise AIUsageLimitExceededError("synthetic limit")


class _NeverCalledResponses:
    async def create(self, **_kwargs: Any) -> Any:
        raise AssertionError("OpenAI must not be called once the budget is used up")


@pytest.mark.asyncio
async def test_openai_client_checks_the_budget_before_every_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations import openai_client as client_module

    monkeypatch.setattr(client_module.settings, "openai_api_key", "sk-synthetic")
    guard = _RecordingGuard(exhausted=True)
    client = OpenAIClient()
    client.use_usage_guard(guard)  # type: ignore[arg-type]
    client._client = SimpleNamespace(responses=_NeverCalledResponses())

    with pytest.raises(AIUsageLimitExceededError):
        await client.create_structured_response(
            model="synthetic",
            system_prompt="s",
            user_input="u",
            json_schema={"type": "object", "properties": {}},
            schema_name="synthetic",
        )
    with pytest.raises(AIUsageLimitExceededError):
        await client.stream_tool_response(
            model="synthetic", input_items=[], tools=[], on_text_delta=_ignore_delta
        )
    assert guard.calls == 2


async def _ignore_delta(_text: str) -> None:
    return None


def _request(forwarded: str | None, host: str = "10.0.0.1") -> Any:
    headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))


def test_client_address_uses_the_entry_added_by_our_edge() -> None:
    # Earlier entries can be forged by the caller; the last one is added by Heroku or Lambda.
    assert client_address(_request("1.2.3.4, 203.0.113.50")) == "203.0.113.50"
    assert client_address(_request("203.0.113.51")) == "203.0.113.51"
    assert client_address(_request(None)) == "10.0.0.1"
