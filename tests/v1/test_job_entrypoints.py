import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app import lambda_jobs
from app.core import aws
from app.core.config import Settings
from app.db.mongo_client import MotorMongoDBClient
from app.services import job_wakeup
from app.services.job_wakeup import LambdaJobWakeup, NoopJobWakeup, wakeup_payload
from app.workers import drain, job_handlers
from app.workers.job_runner import JobHandler, JobKind, JobResult

# --- Wake-ups ------------------------------------------------------------------------------


class RecordingLambdaClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    def invoke(self, **kwargs: Any) -> dict[str, int]:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"StatusCode": 202}


def test_wakeup_payload_names_queues_only() -> None:
    payload = json.loads(wakeup_payload((JobKind.MEDIATION, JobKind.PUSH, JobKind.MEDIATION)))

    assert payload == {"kinds": ["mediation", "push"]}


@pytest.mark.asyncio
async def test_lambda_wakeup_invokes_asynchronously_with_queue_names() -> None:
    client = RecordingLambdaClient()

    await LambdaJobWakeup("bibi-jobs", client=client).wake(JobKind.IMAGE)

    assert client.calls == [
        {"FunctionName": "bibi-jobs", "InvocationType": "Event", "Payload": b'{"kinds": ["image"]}'}
    ]


@pytest.mark.asyncio
async def test_lambda_wakeup_failure_never_reaches_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = RecordingLambdaClient(error=RuntimeError("AccessDenied for arn:secret"))

    await LambdaJobWakeup("bibi-jobs", client=client).wake(JobKind.PUSH)

    assert len(client.calls) == 1
    # Only the error type is logged, never the provider's message.
    assert "arn:secret" not in caplog.text


@pytest.mark.asyncio
async def test_noop_wakeup_and_empty_wakeup_do_nothing() -> None:
    client = RecordingLambdaClient()

    await NoopJobWakeup().wake(JobKind.PUSH)
    await LambdaJobWakeup("bibi-jobs", client=client).wake()

    assert client.calls == []


def test_wakeup_mode_selects_implementation(monkeypatch: pytest.MonkeyPatch) -> None:
    lambda_settings = Settings(
        job_wakeup_mode="lambda", job_wakeup_lambda_function_name="bibi-jobs"
    )
    monkeypatch.setattr(job_wakeup, "get_settings", lambda: lambda_settings)
    job_wakeup.get_job_wakeup.cache_clear()
    try:
        assert isinstance(job_wakeup.get_job_wakeup(), LambdaJobWakeup)
    finally:
        job_wakeup.get_job_wakeup.cache_clear()


def test_lambda_wakeup_requires_function_name() -> None:
    with pytest.raises(ValidationError):
        Settings(job_wakeup_mode="lambda", job_wakeup_lambda_function_name=None)


# --- Lambda handler ------------------------------------------------------------------------


class FakeContext:
    def __init__(self, remaining_ms: int) -> None:
        self.remaining_ms = remaining_ms

    def get_remaining_time_in_millis(self) -> int:
        return self.remaining_ms


def test_lambda_handler_reuses_one_event_loop_and_serves_every_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    built_kinds: list[list[JobKind]] = []

    async def process_one() -> JobResult:
        loops.append(asyncio.get_running_loop())
        return JobResult.IDLE

    def build(_db: object, kinds: Any) -> list[JobHandler]:
        built_kinds.append(list(kinds))
        return [JobHandler(JobKind.PUSH, process_one, timeout_seconds=1, idle_interval_seconds=1)]

    monkeypatch.setattr(lambda_jobs, "get_db", lambda: object())
    monkeypatch.setattr(lambda_jobs, "build_job_handlers", build)
    monkeypatch.setattr(lambda_jobs, "_handlers", None)

    first = lambda_jobs.handler({"kinds": ["mediation"]}, FakeContext(60_000))
    second = lambda_jobs.handler({}, FakeContext(60_000))

    for result in (first, second):
        assert result["processed_total"] == result["failed_total"] == result["timed_out_total"] == 0
    assert len(loops) >= 2
    assert all(loop is loops[0] for loop in loops) and not loops[0].is_closed()
    # Handlers are built once per execution environment, for every queue.
    assert built_kinds == [list(JobKind)]


def test_lambda_handler_respects_remaining_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def process_one() -> JobResult:
        nonlocal calls
        calls += 1
        return JobResult.IDLE

    monkeypatch.setattr(lambda_jobs, "get_db", lambda: object())
    monkeypatch.setattr(
        lambda_jobs,
        "build_job_handlers",
        lambda _db, _kinds: [
            JobHandler(JobKind.ROUTINE, process_one, timeout_seconds=240, idle_interval_seconds=2)
        ],
    )
    monkeypatch.setattr(lambda_jobs, "_handlers", None)

    lambda_jobs.handler({}, FakeContext(60_000))

    # A 240 s routine item cannot fit in a 60 s invocation, so it is left for a later run.
    assert calls == 0


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"kinds": ["push", "nope", 3, "push"]}, ["push"]),
        ({"kinds": "push"}, []),
        ({}, []),
        (None, []),
    ],
)
def test_requested_kinds_ignores_unknown_values(event: Any, expected: list[str]) -> None:
    assert lambda_jobs.requested_kinds(event) == expected


# --- Command line, handlers and in-process flags -------------------------------------------


def test_drain_parses_job_kinds() -> None:
    assert drain.parse_kinds("push, clock") == [JobKind.PUSH, JobKind.CLOCK]
    assert drain.parse_kinds(None) == list(JobKind)
    with pytest.raises(Exception, match="unknown job kind"):
        drain.parse_kinds("push,unknown")


def test_item_timeouts_stay_inside_their_leases() -> None:
    assert job_handlers.within_lease(60) == 45
    assert job_handlers.within_lease(300) == 240


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({}, [JobKind.IMAGE]),
        ({"mediation_worker_enabled": True}, [JobKind.MEDIATION, JobKind.IMAGE]),
        (
            {"xiaobao_in_process_jobs_enabled": True, "image_worker_enabled": False},
            [JobKind.CLOCK, JobKind.PUSH, JobKind.ROUTINE],
        ),
        ({"image_worker_enabled": False}, []),
    ],
)
def test_in_process_job_kinds_follow_flags(
    monkeypatch: pytest.MonkeyPatch, flags: dict[str, bool], expected: list[JobKind]
) -> None:
    monkeypatch.setattr(job_handlers, "settings", Settings(**flags))

    assert job_handlers.in_process_job_kinds() == expected


def test_build_job_handlers_is_ordered_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(kind: JobKind) -> Any:
        return lambda _db: JobHandler(kind, lambda: None, 1, 1)  # type: ignore[arg-type, return-value]

    monkeypatch.setattr(job_handlers, "_BUILDERS", {kind: fake(kind) for kind in JobKind})

    handlers = job_handlers.build_job_handlers(
        object(), [JobKind.IMAGE, JobKind.PUSH, JobKind.IMAGE]
    )

    assert [h.kind for h in handlers] == [JobKind.PUSH, JobKind.IMAGE]


# --- Infrastructure settings ---------------------------------------------------------------


def _aws_settings(**overrides: object) -> Settings:
    # Never read the developer's .env: these tests must not see real credentials.
    base: dict[str, object] = {"aws_region": "eu-west-1"}
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[call-arg]


@pytest.fixture
def fresh_aws_sessions() -> Any:
    aws._session.cache_clear()
    yield
    aws._session.cache_clear()


def test_s3_session_uses_heroku_keys_and_bucket_region(
    monkeypatch: pytest.MonkeyPatch, fresh_aws_sessions: None
) -> None:
    monkeypatch.setattr(
        aws,
        "get_settings",
        lambda: _aws_settings(
            aws_access_key="AKIAEXAMPLE", aws_secret_key="example-secret", aws_s3_region="eu-west-1"
        ),
    )

    session = aws.get_s3_session()

    credentials = session.get_credentials()
    assert credentials is not None and credentials.access_key == "AKIAEXAMPLE"
    assert session.region_name == "eu-west-1"


def test_lambda_region_does_not_leak_into_s3(
    monkeypatch: pytest.MonkeyPatch, fresh_aws_sessions: None
) -> None:
    # On Lambda, AWS_REGION is the function's region; the bucket region is set explicitly.
    monkeypatch.setattr(
        aws,
        "get_settings",
        lambda: _aws_settings(aws_region="eu-central-1", aws_s3_region="eu-west-1"),
    )

    assert aws.get_s3_session().region_name == "eu-west-1"
    assert aws.get_job_wakeup_session().region_name == "eu-central-1"


def test_wakeup_uses_separate_invoke_only_credentials(
    monkeypatch: pytest.MonkeyPatch, fresh_aws_sessions: None
) -> None:
    monkeypatch.setattr(
        aws,
        "get_settings",
        lambda: _aws_settings(
            aws_access_key="AKIAS3ONLY",
            aws_secret_key="s3-secret",
            job_wakeup_aws_access_key="AKIAINVOKEONLY",
            job_wakeup_aws_secret_key="invoke-secret",
            job_wakeup_lambda_region="eu-central-1",
        ),
    )

    wakeup = aws.get_job_wakeup_session()
    s3 = aws.get_s3_session()

    assert wakeup.get_credentials().access_key == "AKIAINVOKEONLY"  # type: ignore[union-attr]
    assert wakeup.region_name == "eu-central-1"
    assert s3.get_credentials().access_key == "AKIAS3ONLY"  # type: ignore[union-attr]


def test_sessions_fall_back_to_default_credential_chain(
    monkeypatch: pytest.MonkeyPatch, fresh_aws_sessions: None
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAFROMCHAIN")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "chain-secret")
    monkeypatch.setattr(aws, "get_settings", lambda: _aws_settings())

    for session in (aws.get_s3_session(), aws.get_job_wakeup_session()):
        credentials = session.get_credentials()
        assert credentials is not None and credentials.access_key == "AKIAFROMCHAIN"


@pytest.mark.parametrize(
    "fields",
    [
        {"aws_access_key": "AKIAEXAMPLE"},
        {"job_wakeup_aws_secret_key": "only-the-secret"},
    ],
)
def test_half_configured_key_pairs_are_rejected(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(_env_file=None, **fields)  # type: ignore[call-arg]


def test_mongo_pool_size_is_configurable() -> None:
    # Constructing the client does not connect.
    client = MotorMongoDBClient("mongodb://127.0.0.1:1", max_pool_size=5)
    try:
        assert client.client.options.pool_options.max_pool_size == 5
    finally:
        client.client.close()


# --- Web startup ---------------------------------------------------------------------------


@pytest.mark.parametrize("ensure_on_startup", [True, False])
@pytest.mark.asyncio
async def test_web_startup_flags(monkeypatch: pytest.MonkeyPatch, ensure_on_startup: bool) -> None:
    from app import main

    ensured: list[object] = []
    started: list[list[JobKind]] = []

    async def ensure(db: object) -> None:
        ensured.append(db)

    async def run_in_process(kinds: list[JobKind], stop_event: asyncio.Event) -> None:
        started.append(kinds)
        await stop_event.wait()

    monkeypatch.setattr(
        main, "settings", SimpleNamespace(ensure_indexes_on_startup=ensure_on_startup)
    )
    monkeypatch.setattr(main, "ensure_all_indexes", ensure)
    monkeypatch.setattr(main, "get_db", lambda: object())
    monkeypatch.setattr(main, "in_process_job_kinds", lambda: [JobKind.IMAGE])
    monkeypatch.setattr(main, "run_in_process_jobs", run_in_process)

    async with main.lifespan(main.app):
        await asyncio.sleep(0)

    assert len(ensured) == (1 if ensure_on_startup else 0)
    assert started == [[JobKind.IMAGE]]


@pytest.mark.asyncio
async def test_broken_job_dependencies_do_not_stop_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    def broken(_db: object, _kinds: object) -> list[JobHandler]:
        raise RuntimeError("OPENAI_API_KEY missing")

    monkeypatch.setattr(main, "get_db", lambda: object())
    monkeypatch.setattr(main, "build_job_handlers", broken)

    await asyncio.wait_for(main.run_in_process_jobs([JobKind.MEDIATION], asyncio.Event()), 1)


def test_tests_never_see_real_credentials() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    for name in (
        "aws_access_key",
        "aws_secret_key",
        "job_wakeup_aws_access_key",
        "job_wakeup_aws_secret_key",
        "access_key_danfeng",
        "access_key_joris",
        "aerodatabox_api_key",
        "openai_api_key",
    ):
        assert not getattr(settings, name), f"{name} leaked into the test environment"
    aws._session.cache_clear()
    try:
        assert aws.get_s3_session().get_credentials() is None
    finally:
        aws._session.cache_clear()
