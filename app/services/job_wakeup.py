"""Tell the background job runner that new work is waiting.

A wake-up is only a hint. The work itself is already stored durably in MongoDB, and a periodic
runner (the Heroku worker loop, or a scheduled invocation in serverless deployments) picks it up
even when a wake-up is lost. Wake-ups therefore never fail the request that triggered them, and
their payload names queues only: no identifiers, user content or other personal data.
"""

import asyncio
import json
from functools import lru_cache
from typing import Protocol

from app.core.aws import get_aws_session
from app.core.config import get_settings
from app.core.logging import get_logger
from app.workers.job_runner import JobKind

logger = get_logger(__name__)


class JobWakeup(Protocol):
    async def wake(self, *kinds: JobKind) -> None: ...


class NoopJobWakeup:
    """Used when a continuously running worker polls the queues anyway."""

    async def wake(self, *kinds: JobKind) -> None:
        return None


def wakeup_payload(kinds: tuple[JobKind, ...]) -> bytes:
    return json.dumps({"kinds": sorted({kind.value for kind in kinds})}).encode()


class LambdaJobWakeup:
    """Invoke the job function asynchronously ("Event" invocation) and return immediately."""

    def __init__(self, function_name: str, client: object | None = None) -> None:
        self._function_name = function_name
        self._client = client

    def _lambda_client(self) -> object:
        if self._client is None:
            self._client = get_aws_session().client("lambda")
        return self._client

    async def wake(self, *kinds: JobKind) -> None:
        if not kinds:
            return
        payload = wakeup_payload(kinds)
        try:
            client = self._lambda_client()
            await asyncio.to_thread(
                client.invoke,  # type: ignore[attr-defined]
                FunctionName=self._function_name,
                InvocationType="Event",
                Payload=payload,
            )
        except Exception as exc:
            # The scheduled run recovers the work; never surface this to the user.
            logger.warning(
                "Background job wake-up failed",
                extra={
                    "job_kinds": [kind.value for kind in kinds],
                    "error_type": type(exc).__name__,
                },
            )


@lru_cache
def get_job_wakeup() -> JobWakeup:
    settings = get_settings()
    if settings.job_wakeup_mode == "lambda" and settings.job_wakeup_lambda_function_name:
        return LambdaJobWakeup(settings.job_wakeup_lambda_function_name)
    return NoopJobWakeup()
