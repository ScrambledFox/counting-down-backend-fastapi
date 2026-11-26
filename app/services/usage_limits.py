"""Login brute-force protection and AI cost guards (ADR 0001, Phase 3 gate).

The API is exposed on a public Lambda Function URL without API Gateway throttling, so these
limits are enforced by the application with shared MongoDB counters:

* Failed logins: per client address and in total. Only failures count, so the two users are
  never locked out by their own successful logins.
* AI requests: one daily budget for every OpenAI generation (chat, mediation, routines).
* Mediation AI runs: a daily allowance per person for actions that start mediation AI work.

Client addresses are stored only as a short hash.
"""

import hashlib
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.repositories.usage_counters import UsageCounterRepository
from app.schemas.v1.exceptions import TooManyRequestsException
from app.schemas.v1.user import UserType

settings = get_settings()

DAY_SECONDS = 24 * 60 * 60


class AIUsageLimitExceededError(RuntimeError):
    """Today's AI request budget is used up; the work can be retried tomorrow."""


def client_address(request: Request) -> str:
    """The caller's address as seen by our edge.

    Heroku's router and Lambda Function URLs both add the address they received the connection
    from as the last ``X-Forwarded-For`` entry; earlier entries can be set by the client. Without
    the header (local development) the socket address is used.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    if entries:
        return entries[-1]
    return request.client.host if request.client else "unknown"


def _client_scope(address: str) -> str:
    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]
    return f"login_failures:client:{digest}"


GLOBAL_LOGIN_SCOPE = "login_failures:all"


class LoginAttemptGuard:
    def __init__(self, counters: Annotated[UsageCounterRepository, Depends()]) -> None:
        self._counters = counters

    async def ensure_allowed(self, address: str) -> None:
        per_client = settings.login_max_failures_per_client
        if per_client > 0:
            failures = await self._counters.current(
                _client_scope(address), settings.login_failure_window_seconds
            )
            if failures >= per_client:
                raise TooManyRequestsException(
                    "Too many failed login attempts. Please try again later.",
                    retry_after=settings.login_failure_window_seconds,
                )
        overall = settings.login_max_failures_global
        if overall > 0:
            failures = await self._counters.current(
                GLOBAL_LOGIN_SCOPE, settings.login_global_failure_window_seconds
            )
            if failures >= overall:
                raise TooManyRequestsException(
                    "Login is temporarily paused after many failed attempts. "
                    "Please try again later.",
                    retry_after=settings.login_global_failure_window_seconds,
                )

    async def record_failure(self, address: str) -> None:
        await self._counters.increment(
            _client_scope(address), settings.login_failure_window_seconds
        )
        await self._counters.increment(
            GLOBAL_LOGIN_SCOPE, settings.login_global_failure_window_seconds
        )


AI_REQUESTS_SCOPE = "ai_requests:all"


def _mediation_scope(owner: UserType) -> str:
    return f"mediation_ai_runs:{owner.value}"


class AIUsageGuard:
    """Daily AI budgets. Works with or without FastAPI dependency injection.

    Background jobs construct ``OpenAIClient()`` directly, so the counter repository is created
    lazily from the application database when none is given.
    """

    def __init__(
        self,
        counters: Annotated[UsageCounterRepository | None, Depends(UsageCounterRepository)] = None,
    ) -> None:
        self._counters = counters

    def _repository(self) -> UsageCounterRepository:
        if self._counters is None:
            self._counters = UsageCounterRepository(get_db())
        return self._counters

    async def ensure_ai_available(self) -> None:
        """Refuse up front (HTTP 429) when today's AI budget is already used up."""
        limit = settings.ai_daily_request_limit
        if limit <= 0:
            return
        used = await self._repository().current(AI_REQUESTS_SCOPE, DAY_SECONDS)
        if used >= limit:
            raise TooManyRequestsException(
                "Xiao Bao has reached today's limit. Please try again tomorrow."
            )

    async def consume_ai_request(self) -> None:
        """Count one AI generation; raise once the daily budget is exceeded."""
        limit = settings.ai_daily_request_limit
        if limit <= 0:
            return
        used = await self._repository().increment(AI_REQUESTS_SCOPE, DAY_SECONDS)
        if used > limit:
            raise AIUsageLimitExceededError("The daily AI request limit has been reached")

    async def consume_mediation_run(self, owner: UserType) -> None:
        """Count one user action that starts mediation AI work (HTTP 429 when over)."""
        limit = settings.mediation_ai_daily_runs_per_user
        if limit <= 0:
            return
        used = await self._repository().increment(_mediation_scope(owner), DAY_SECONDS)
        if used > limit:
            raise TooManyRequestsException(
                "You've reached today's limit for Xiao Bao in mediation. Please try again tomorrow."
            )
