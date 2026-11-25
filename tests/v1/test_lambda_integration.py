"""Phase 2 Lambda integration: secrets loading, deployment tasks, production rules, health."""

from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError

from app import lambda_jobs
from app.core import ssm
from app.core.config import Settings, get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.util.time import utc_now
from app.workers.job_health import overdue_work_seconds

settings = get_settings()


# --- SSM --------------------------------------------------------------------------------------


class FakeSSM:
    def __init__(self, pages: list[list[dict[str, str]]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def get_paginator(self, name: str) -> FakeSSM:
        assert name == "get_parameters_by_path"
        return self

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return [{"Parameters": page} for page in self.pages]


def test_ssm_parameters_become_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSM_PARAMETER_PATH", "/bibi/test/jobs")
    monkeypatch.delenv("SYNTHETIC_SECRET", raising=False)
    monkeypatch.delenv("OTHER_SECRET", raising=False)
    client = FakeSSM(
        [
            [{"Name": "/bibi/test/jobs/SYNTHETIC_SECRET", "Value": "s1"}],
            [{"Name": "/bibi/test/jobs/OTHER_SECRET", "Value": "s2"}],
        ]
    )

    loaded = ssm.load_parameters_into_environ(client)

    assert loaded == ["OTHER_SECRET", "SYNTHETIC_SECRET"]
    assert client.calls == [{"Path": "/bibi/test/jobs", "WithDecryption": True, "Recursive": False}]
    import os

    assert os.environ["SYNTHETIC_SECRET"] == "s1"
    monkeypatch.delenv("SYNTHETIC_SECRET")
    monkeypatch.delenv("OTHER_SECRET")


def test_without_a_parameter_path_nothing_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSM_PARAMETER_PATH", raising=False)

    assert ssm.load_parameters_into_environ(FakeSSM([])) == []


# --- Deployment tasks ---------------------------------------------------------------------------


class FakeDB:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def command(self, name: str) -> dict[str, int]:
        self.commands.append(name)
        return {"ok": 1}


class FakeContext:
    def get_remaining_time_in_millis(self) -> int:
        return 60_000


def test_smoke_task_checks_mongo_without_processing_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB()
    monkeypatch.setattr(lambda_jobs, "get_db", lambda: db)

    def must_not_build(*_args: object) -> None:
        raise AssertionError("smoke must not process jobs")

    monkeypatch.setattr(lambda_jobs, "build_job_handlers", must_not_build)

    result = lambda_jobs.handler({"task": "smoke"}, FakeContext())

    assert result["mongo"] == "ok" and db.commands == ["ping"]
    assert set(result) == {
        "task",
        "mongo",
        "push_configured",
        "openai_configured",
        "parameters_loaded",
    }


def test_ensure_indexes_task_runs_the_index_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    async def ensure(db: object) -> None:
        called.append(db)

    db = FakeDB()
    monkeypatch.setattr(lambda_jobs, "get_db", lambda: db)
    monkeypatch.setattr(lambda_jobs, "ensure_all_indexes", ensure)

    assert lambda_jobs.handler({"task": "ensure_indexes"}, FakeContext())["ok"] is True
    assert called == [db]


def test_unknown_tasks_fail_the_invocation() -> None:
    with pytest.raises(ValueError):
        lambda_jobs.handler({"task": "drop_everything"}, FakeContext())


# --- Production rules ---------------------------------------------------------------------------


def prod_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "prod",
        "mongo_url": "mongodb+srv://synthetic.example.net/",
        "access_key_danfeng": "d",
        "access_key_joris": "j",
    }
    return Settings(_env_file=None, **{**base, **overrides})  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "url",
    [
        "mongodb+srv://synthetic.example.net/?tlsAllowInvalidCertificates=true",
        "mongodb://synthetic.example.net/?tlsInsecure=true",
        "mongodb://synthetic.example.net/?tls=false",
    ],
)
def test_production_rejects_mongo_urls_without_certificate_verification(url: str) -> None:
    with pytest.raises(ValidationError, match="TLS"):
        prod_settings(mongo_url=url)


def test_jobs_function_runs_in_production_without_login_keys() -> None:
    with pytest.raises(ValidationError, match="access key"):
        prod_settings(access_key_danfeng=None, access_key_joris=None)

    jobs = prod_settings(
        access_key_danfeng=None, access_key_joris=None, auth_access_keys_required=False
    )

    assert jobs.app_env == "prod"


# --- Overdue work -----------------------------------------------------------------------------


@pytest_asyncio.fixture
async def health_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    names = (
        settings.xiaobao_routines_collection_name,
        settings.xiaobao_routine_runs_collection_name,
        settings.xiaobao_push_deliveries_collection_name,
    )
    for name in names:
        await db[name].delete_many({})
    yield db
    for name in names:
        await db[name].delete_many({})


@pytest.mark.asyncio
async def test_overdue_work_reports_ages_of_unprocessed_routines_and_pushes(
    health_db: AsyncDB,
) -> None:
    now = utc_now()
    assert await overdue_work_seconds(health_db, now) == {
        "oldest_overdue_routine_seconds": 0,
        "oldest_pending_push_seconds": 0,
    }

    await health_db[settings.xiaobao_routines_collection_name].insert_many(
        [
            {"enabled": True, "deleted_at": None, "next_run_at": now - timedelta(minutes=12)},
            # Paused or not yet due routines are not overdue.
            {"enabled": False, "deleted_at": None, "next_run_at": now - timedelta(hours=5)},
            {"enabled": True, "deleted_at": None, "next_run_at": now + timedelta(minutes=5)},
        ]
    )
    await health_db[settings.xiaobao_push_deliveries_collection_name].insert_many(
        [
            {"status": "PENDING", "attempt_count": 0, "available_at": now - timedelta(minutes=3)},
            {"status": "DELIVERED", "attempt_count": 1, "available_at": now - timedelta(hours=1)},
        ]
    )

    health = await overdue_work_seconds(health_db, now)

    assert 715 <= health["oldest_overdue_routine_seconds"] <= 725
    assert 175 <= health["oldest_pending_push_seconds"] <= 185
