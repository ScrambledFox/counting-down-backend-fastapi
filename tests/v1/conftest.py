from collections.abc import AsyncGenerator
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.core.config import settings
from app.db.client import AsyncDB, get_db
from app.repositories.todo import TodoRepository
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate
from app.services.todo import TodoService


# Unit test fixtures (with mocks)
@pytest.fixture
def todo_repository_mock():
    repo_mock = AsyncMock(spec=TodoRepository)
    return repo_mock


@pytest.fixture
def todo_service_mock(todo_repository_mock: TodoRepository):
    """Service with mocked repository for unit tests."""
    return TodoService(repo=todo_repository_mock)


# Integration test fixtures (real database)
@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncDB]:
    """Real database connection for integration tests."""
    db = await get_db()
    collection = db[settings.todos_collection_name]
    # Clean up before test
    await collection.delete_many({})
    yield db
    # Clean up after test
    await collection.delete_many({})


@pytest_asyncio.fixture
async def todo_repository_real(test_db: AsyncDB):
    """Real repository for integration tests."""
    return TodoRepository(db=test_db)


@pytest_asyncio.fixture
async def todo_service_real(todo_repository_real: TodoRepository):
    """Service with real repository for integration tests."""
    return TodoService(repo=todo_repository_real)


# Sample data fixtures
@pytest.fixture
def sample_todos() -> list[Todo]:
    return [
        Todo(
            _id="64a7f0c2f1d2c4b5a6e7d8f1",
            title="Test Todo 1",
            category="Testing",
            completed=False,
            created_at=datetime.fromisoformat("2024-07-01T12:00:00Z"),
            updated_at=None,
        ),
        Todo(
            _id="64a7f0c2f1d2c4b5a6e7d8f2",
            title="Test Todo 2",
            category="Testing",
            completed=True,
            created_at=datetime.fromisoformat("2024-07-02T12:00:00Z"),
            updated_at=datetime.fromisoformat("2024-07-03T12:00:00Z"),
        ),
    ]


@pytest.fixture
def sample_todo() -> Todo:
    return Todo(
        _id="64a7f0c2f1d2c4b5a6e7d8f1",
        title="Sample Todo",
        category="General",
        completed=False,
        created_at=datetime.fromisoformat("2024-07-01T12:00:00Z"),
        updated_at=None,
    )


@pytest.fixture
def sample_todo_create() -> TodoCreate:
    return TodoCreate(
        title="New Todo",
        category="General",
        completed=False,
    )


@pytest.fixture
def sample_todo_update() -> TodoUpdate:
    return TodoUpdate(
        title="Updated Todo",
    )
