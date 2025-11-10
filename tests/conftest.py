"""Test configuration and fixtures."""
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings
from app.main import app
from app.repositories.todos import TodoRepository
from app.services.deps import get_todo_service
from app.services.todos import TodoService


@pytest.fixture
def mock_db():
    """Mock MongoDB database."""
    db = MagicMock()
    collection = MagicMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db


@pytest.fixture
def mock_repository(mock_db):
    """Mock TodoRepository."""
    repo = TodoRepository(mock_db)
    return repo


@pytest.fixture
def mock_service(mock_repository):
    """Mock TodoService."""
    service = TodoService(mock_repository)
    return service


@pytest.fixture
def client(mock_service):
    """FastAPI test client with mocked service."""
    
    def override_get_todo_service():
        return mock_service
    
    app.dependency_overrides[get_todo_service] = override_get_todo_service
    
    with TestClient(app) as client:
        yield client
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_todo_item():
    """Sample todo item data."""
    return {
        "id": "507f1f77bcf86cd799439011",
        "title": "Test Todo",
        "category": "personal",
        "completed": False,
        "created_at": "2025-11-10T10:00:00Z",
        "updated_at": "2025-11-10T10:00:00Z",
    }


@pytest.fixture
def sample_todo_items():
    """Multiple sample todo items."""
    return [
        {
            "id": "507f1f77bcf86cd799439011",
            "title": "First Todo",
            "category": "personal",
            "completed": False,
            "created_at": "2025-11-10T10:00:00Z",
            "updated_at": "2025-11-10T10:00:00Z",
        },
        {
            "id": "507f1f77bcf86cd799439012",
            "title": "Second Todo",
            "category": "work",
            "completed": True,
            "created_at": "2025-11-10T11:00:00Z",
            "updated_at": "2025-11-10T11:00:00Z",
        },
        {
            "id": "507f1f77bcf86cd799439013",
            "title": "Third Todo",
            "category": "shopping",
            "completed": False,
            "created_at": "2025-11-10T12:00:00Z",
            "updated_at": "2025-11-10T12:00:00Z",
        },
    ]


# Integration test fixtures


@pytest.fixture(scope="session")
def test_db_name():
    """Test database name."""
    return f"{settings.mongo_db_name}_test"


@pytest_asyncio.fixture(scope="function")
async def test_db(test_db_name: str) -> AsyncIterator[AsyncIOMotorDatabase]:
    """
    Create a test database for each test function.
    Cleans up after each test.
    """
    client = AsyncIOMotorClient(settings.mongo_url)
    db = client[test_db_name]
    
    yield db
    
    # Cleanup: drop the test database after each test
    await client.drop_database(test_db_name)
    client.close()


@pytest_asyncio.fixture
async def integration_client(
    test_db: AsyncIOMotorDatabase,
) -> AsyncIterator[AsyncClient]:
    """
    AsyncClient for integration tests with test database.
    Overrides the database dependency to use test database.
    """
    from app.db.deps import get_db
    
    async def override_get_db():
        yield test_db
    
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    
    app.dependency_overrides.clear()


@pytest.fixture
def sample_todo_data():
    """Sample todo item creation data."""
    return {
        "title": "Buy groceries",
        "category": "personal",
        "completed": False,
    }


@pytest.fixture
def sample_todo_data_list():
    """Multiple sample todo items for bulk operations."""
    return [
        {
            "title": "Write tests",
            "category": "work",
            "completed": False,
        },
        {
            "title": "Review PR",
            "category": "work",
            "completed": True,
        },
        {
            "title": "Buy milk",
            "category": "shopping",
            "completed": False,
        },
    ]
