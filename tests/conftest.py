# ruff: noqa: E402  (app imports must follow the credential guard below)
"""Shared test configuration.

Credential guard: tests must never load a developer's real credentials (from ``.env``,
``~/.aws`` or instance metadata) or print their identifiers. Environment variables take
precedence over ``.env`` in pydantic-settings, so blanking them here, before any app module is
imported, keeps real keys out of every test. ``MONGO_URL`` stays configurable because the
integration tests need a database; they only use the dedicated ``test`` database.
"""

import os

_CREDENTIAL_SETTINGS = (
    "AWS_ACCESS_KEY",
    "AWS_SECRET_KEY",
    "JOB_WAKEUP_AWS_ACCESS_KEY",
    "JOB_WAKEUP_AWS_SECRET_KEY",
    "ACCESS_KEY_DANFENG",
    "ACCESS_KEY_JORIS",
    "AERODATABOX_API_KEY",
    "XIAOBAO_WEB_PUSH_VAPID_PRIVATE_KEY",
    "XIAOBAO_WEB_PUSH_SUBSCRIPTION_ENCRYPTION_KEY",
)
for _name in _CREDENTIAL_SETTINGS:
    os.environ[_name] = ""
# Opt-in live model evaluations are the only tests that may use a real OpenAI key.
if os.environ.get("RUN_XIAOBAO_LIVE_EVALS") != "1":
    os.environ["OPENAI_API_KEY"] = ""
# Keep boto3's default credential chain away from local profiles and instance metadata.
for _name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
    os.environ.pop(_name, None)
os.environ["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
os.environ["AWS_CONFIG_FILE"] = os.devnull
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"

from collections.abc import AsyncGenerator

import pytest_asyncio

from app.db.mongo_client import MotorMongoDBClient, get_mongo_client
from app.models.mongo import AsyncClient


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _mongo_client() -> AsyncGenerator[AsyncClient]:
    """Bind one Motor client to the session event loop.

    Why: get_mongo_client is lru_cached for production, so without this fixture
    the first integration test would bind the client's executor to its
    (function-scoped) loop, and every subsequent test would hit
    "Event loop is closed" when reusing the cached client.
    """
    get_mongo_client.cache_clear()
    client = get_mongo_client()
    yield client.client
    if isinstance(client, MotorMongoDBClient):
        client.client.close()
    get_mongo_client.cache_clear()
