"""Test configuration and fixtures."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.dependencies import get_db, get_todo_service
from app.main import app
from app.repositories.todo import TodoRepository
from app.schemas.v1.todo import Todo, TodoCreate
from app.services.todo import TodoService

FIXED_TIME = datetime(2025, 11, 10, 10, 0, 0)


@pytest.fixture
def mock_db():
    """Mock MongoDB database."""
    db = MagicMock()
    collection = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def mock_repository(mock_db: AsyncIOMotorDatabase[Any]) -> TodoRepository:
    """Mock TodoRepository."""
    repo = TodoRepository(mock_db)
    return repo


@pytest.fixture
def mock_service(mock_repository: TodoRepository) -> TodoService:
    """Mock TodoService."""
    service = TodoService(mock_repository)
    return service


@pytest.fixture
def client(mock_service: TodoService):
    """FastAPI test client with mocked service."""

    def override_get_todo_service():
        return mock_service

    app.dependency_overrides[get_todo_service] = override_get_todo_service

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_todo_item() -> Todo:
    """Sample todo item data."""
    return Todo(
        id="507f1f77bcf86cd799439011",
        title="Test Todo",
        category="personal",
        completed=False,
        created_at=datetime.fromisoformat("2025-11-10T10:00:00+00:00"),
        updated_at=datetime.fromisoformat("2025-11-10T10:00:00+00:00"),
    )


@pytest.fixture
def sample_todo_items() -> list[Todo]:
    """Multiple sample todo items."""
    return [
        Todo(
            id="507f1f77bcf86cd799439011",
            title="First Todo",
            category="personal",
            completed=False,
            created_at=datetime.fromisoformat("2025-11-10T10:00:00+00:00"),
            updated_at=datetime.fromisoformat("2025-11-10T10:00:00+00:00"),
        ),
        Todo(
            id="507f1f77bcf86cd799439012",
            title="Second Todo",
            category="work",
            completed=True,
            created_at=datetime.fromisoformat("2025-11-10T11:00:00+00:00"),
            updated_at=datetime.fromisoformat("2025-11-10T11:00:00+00:00"),
        ),
        Todo(
            id="507f1f77bcf86cd799439013",
            title="Third Todo",
            category="shopping",
            completed=False,
            created_at=datetime.fromisoformat("2025-11-10T12:00:00+00:00"),
            updated_at=datetime.fromisoformat("2025-11-10T12:00:00+00:00"),
        ),
    ]


# Integration test fixtures


@pytest.fixture(scope="session")
def test_db_name():
    """Test database name."""
    return f"{settings.mongo_app_name}_test"


@pytest_asyncio.fixture(scope="function")
async def test_db(test_db_name: str) -> AsyncIterator[AsyncIOMotorDatabase[Any]]:
    """
    Create a test database for each test function.
    Cleans up after each test.
    """
    client = AsyncIOMotorClient[Any](settings.mongo_url)
    db = client[test_db_name]

    yield db

    # Cleanup: drop the test database after each test
    await client.drop_database(test_db_name)
    client.close()


@pytest_asyncio.fixture
async def integration_client(
    test_db: AsyncIOMotorDatabase[Any],
) -> AsyncIterator[AsyncClient]:
    """
    AsyncClient for integration tests with test database.
    Overrides the database dependency to use test database.
    """
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_todo_data() -> TodoCreate:
    """Sample todo item creation data."""
    return TodoCreate(title="Buy groceries", category="personal", completed=False)


@pytest.fixture
def sample_todo_data_list() -> list[TodoCreate]:
    """Multiple sample todo items for bulk operations."""
    return [
        TodoCreate(title="Write tests", category="work", completed=False),
        TodoCreate(title="Review PR", category="work", completed=True),
        TodoCreate(title="Buy milk", category="shopping", completed=False),
    ]
