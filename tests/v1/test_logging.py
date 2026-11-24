import json
import logging
import time
from collections.abc import Iterator

import pytest

from app.core.logging import LOG_NAME, StructuredFormatter, error_fields
from app.workers.job_runner import JobHandler, JobKind, JobRunSummary, log_job_run_summary, run_jobs

PRIVATE = "she said the argument about the move still hurts"


@pytest.fixture
def app_logs(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture the app logger directly; setup_logging() disables propagation to the root."""
    app_logger = logging.getLogger(LOG_NAME)
    app_logger.addHandler(caplog.handler)
    previous_level = app_logger.level
    app_logger.setLevel(logging.DEBUG)
    yield caplog
    app_logger.removeHandler(caplog.handler)
    app_logger.setLevel(previous_level)


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        "counting_down.test", logging.INFO, __file__, 1, "Background job run finished", None, None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_text_format_renders_allowlisted_fields_only() -> None:
    record = make_record(job_kind="push", failed={"push": 1}, content=PRIVATE, prompt=PRIVATE)

    line = StructuredFormatter(json_output=False).format(record)

    assert 'job_kind="push"' in line
    assert 'failed={"push":1}' in line
    assert PRIVATE not in line and "prompt" not in line


def test_json_format_is_one_parseable_object_with_allowlisted_fields() -> None:
    record = make_record(event="job_run_summary", failed_total=2, response_body=PRIVATE)

    payload = json.loads(StructuredFormatter(json_output=True).format(record))

    assert payload["event"] == "job_run_summary"
    assert payload["failed_total"] == 2
    assert payload["level"] == "INFO" and payload["message"] == "Background job run finished"
    assert "response_body" not in payload


def test_error_fields_describe_type_and_location_without_the_message() -> None:
    try:
        raise ValueError(PRIVATE)
    except ValueError as exc:
        fields = error_fields(exc)

    assert fields["error_type"] == "ValueError"
    assert PRIVATE not in json.dumps(fields)


@pytest.mark.asyncio
async def test_runner_failure_log_never_contains_the_exception_message(
    app_logs: pytest.LogCaptureFixture,
) -> None:
    async def leaky() -> bool:
        raise RuntimeError(f"provider rejected prompt: {PRIVATE}")

    await run_jobs(
        [JobHandler(JobKind.MEDIATION, leaky, timeout_seconds=1, idle_interval_seconds=1)],
        deadline=time.monotonic() + 30,
    )

    failures = [r for r in app_logs.records if getattr(r, "event", None) == "job_failed"]
    assert len(failures) == 1
    record = failures[0]
    assert record.exc_info is None
    rendered = StructuredFormatter(json_output=True).format(record)
    assert PRIVATE not in rendered
    payload = json.loads(rendered)
    assert payload["job_kind"] == "mediation"
    assert payload["error_type"] == "RuntimeError"
    assert "duration_ms" in payload


@pytest.mark.parametrize(
    ("summary", "level", "outcome"),
    [
        (JobRunSummary(processed={"push": 2}), logging.INFO, "ok"),
        (
            JobRunSummary(processed={"push": 1}, failed={"routine": 1}),
            logging.WARNING,
            "unsuccessful_items",
        ),
        (JobRunSummary(timed_out={"image": 1}), logging.WARNING, "unsuccessful_items"),
    ],
)
def test_run_summary_exposes_unsuccessful_items_even_when_the_run_returns(
    app_logs: pytest.LogCaptureFixture, summary: JobRunSummary, level: int, outcome: str
) -> None:
    log_job_run_summary(summary, requested_kinds=["push"])

    (record,) = [r for r in app_logs.records if getattr(r, "event", None) == "job_run_summary"]
    payload = json.loads(StructuredFormatter(json_output=True).format(record))
    assert record.levelno == level
    assert payload["outcome"] == outcome
    assert payload["failed_total"] == sum(summary.failed.values())
    assert payload["timed_out_total"] == sum(summary.timed_out.values())
    assert payload["processed_total"] == sum(summary.processed.values())
    assert payload["requested_kinds"] == ["push"]
