"""The mediation output unique-index migration on the shared ``test`` database (synthetic data)."""

import asyncio
import importlib.util
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from types import ModuleType

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.mongo_client import get_test_db
from app.models.mongo import AsyncDB
from app.repositories.mediation import MediationCommentRepository

settings = get_settings()
SESSION_ID = "64b64c000000000000000601"
JOB_ID = "64b64c000000000000000602"
SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "migrate_mediation_output_unique_index.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate_mediation_output_unique_index", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


migration = load_migration()


@pytest_asyncio.fixture
async def output_db() -> AsyncGenerator[AsyncDB]:
    db = get_test_db()
    names = migration.output_collections()

    async def reset() -> None:
        for name in names:
            await db[name].delete_many({})
            if migration.INDEX_NAME in await db[name].index_information():
                await db[name].drop_index(migration.INDEX_NAME)

    await reset()
    yield db
    await reset()


@pytest.mark.asyncio
async def test_duplicates_block_the_migration_and_nothing_is_deleted(
    output_db: AsyncDB, capsys: pytest.CaptureFixture[str]
) -> None:
    comments = output_db[settings.mediation_comments_collection_name]
    await comments.insert_many(
        [
            {"session_id": SESSION_ID, "content": "synthetic A", "ai_job_id": "job-dup"},
            {"session_id": SESSION_ID, "content": "synthetic B", "ai_job_id": "job-dup"},
            {"session_id": SESSION_ID, "content": "human comment without a job"},
        ]
    )

    exit_code = await migration.run(output_db, apply=True)

    assert exit_code == 1
    assert await comments.count_documents({}) == 3
    assert not await migration.unique_index_exists(
        output_db, settings.mediation_comments_collection_name
    )
    printed = capsys.readouterr().out
    assert "job-dup" in printed and "synthetic" not in printed


@pytest.mark.asyncio
async def test_clean_collections_get_unique_indexes_idempotently(output_db: AsyncDB) -> None:
    assert await migration.run(output_db, apply=False) == 0
    for name in migration.output_collections():
        assert not await migration.unique_index_exists(output_db, name)

    assert await migration.run(output_db, apply=True) == 0
    assert await migration.run(output_db, apply=True) == 0
    for name in migration.output_collections():
        assert await migration.unique_index_exists(output_db, name)


@pytest.mark.asyncio
async def test_after_migration_concurrent_outputs_for_one_job_store_exactly_one(
    output_db: AsyncDB,
) -> None:
    assert await migration.run(output_db, apply=True) == 0
    comments = MediationCommentRepository(output_db)

    stored = await asyncio.gather(
        *(comments.create_ai_comment(SESSION_ID, None, f"reply {i}", JOB_ID) for i in range(8))
    )

    assert len({comment.id for comment in stored}) == 1
    collection = output_db[settings.mediation_comments_collection_name]
    assert await collection.count_documents({"ai_job_id": JOB_ID}) == 1
    # Outputs without a job (for example Xiao Bao's own comments) are unaffected.
    await comments.create_ai_comment(SESSION_ID, None, "no job", None)
    await comments.create_ai_comment(SESSION_ID, None, "no job either", None)
    assert await collection.count_documents({"ai_job_id": {"$exists": False}}) == 2


def test_apply_requires_confirming_the_configured_database() -> None:
    with pytest.raises(SystemExit):
        migration.main(["--apply", "--confirm-database", "not-the-configured-db"])
