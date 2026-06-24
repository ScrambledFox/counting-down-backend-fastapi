from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import Depends

from app.core.config import get_settings
from app.db.mongo_client import AsyncDB, get_test_db
from app.repositories.airport import AirportRepository
from app.repositories.todo import TodoRepository
from app.schemas.v1.airport import Airport, AirportCreate
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate
from app.services.airport import AirportService
from app.services.todo import TodoService

settings = get_settings()


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
    db = get_test_db()
    collection = db[settings.todos_collection_name]
    # Clean up before test
    await collection.delete_many({})
    yield db
    # Clean up after test
    await collection.delete_many({})


@pytest_asyncio.fixture
async def todo_repository_real(test_db: Annotated[AsyncDB, Depends(get_test_db)]):
    """Real repository for integration tests."""
    return TodoRepository(db=test_db)


@pytest_asyncio.fixture
async def todo_service_real(todo_repository_real: Annotated[TodoRepository, Depends()]):
    """Service with real repository for integration tests."""
    return TodoService(repo=todo_repository_real)


# Sample data fixtures
@pytest.fixture
def sample_todos() -> list[Todo]:
    return [
        Todo(
            id="64a7f0c2f1d2c4b5a6e7d8f1",
            title="Test Todo 1",
            category="Testing",
            completed=False,
            created_at=datetime.fromisoformat("2024-07-01T12:00:00Z"),
            updated_at=None,
        ),
        Todo(
            id="64a7f0c2f1d2c4b5a6e7d8f2",
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
        id="64a7f0c2f1d2c4b5a6e7d8f1",
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


# Airport unit test fixtures (with mocks)
@pytest.fixture
def airport_repository_mock():
    return AsyncMock(spec=AirportRepository)


@pytest.fixture
def airport_service_mock(airport_repository_mock: AirportRepository):
    """Service with mocked repository for unit tests."""
    return AirportService(repo=airport_repository_mock)


# Airport integration test fixtures (real database)
@pytest_asyncio.fixture
async def airport_test_db() -> AsyncGenerator[AsyncDB]:
    """Real database connection for airport integration tests."""
    db = get_test_db()
    collection = db[settings.airports_collection_name]
    await collection.delete_many({})
    yield db
    await collection.delete_many({})


@pytest_asyncio.fixture
async def airport_repository_real(airport_test_db: Annotated[AsyncDB, Depends(get_test_db)]):
    return AirportRepository(db=airport_test_db)


@pytest_asyncio.fixture
async def airport_service_real(airport_repository_real: Annotated[AirportRepository, Depends()]):
    return AirportService(repo=airport_repository_real)


@pytest.fixture
def sample_airport_creates() -> list[AirportCreate]:
    return [
        AirportCreate(
            icao="EHAM",
            iata="AMS",
            name="Amsterdam Airport Schiphol",
            city="Amsterdam",
            country="Netherlands",
            longitude=4.76389,
            latitude=52.3086,
        ),
        AirportCreate(
            icao="KJFK",
            iata="JFK",
            name="John F Kennedy International Airport",
            city="New York",
            country="United States",
            longitude=-73.778692,
            latitude=40.639928,
        ),
        AirportCreate(
            icao="EGLL",
            iata="LHR",
            name="London Heathrow Airport",
            city="London",
            country="United Kingdom",
            longitude=-0.461941,
            latitude=51.4706,
        ),
    ]


@pytest.fixture
def sample_airports() -> list[Airport]:
    base = datetime.fromisoformat("2024-07-01T12:00:00Z")
    return [
        Airport(
            id="64a7f0c2f1d2c4b5a6e7d901",
            icao="EHAM",
            iata="AMS",
            name="Amsterdam Airport Schiphol",
            city="Amsterdam",
            country="Netherlands",
            longitude=4.76389,
            latitude=52.3086,
            created_at=base,
            updated_at=None,
        ),
        Airport(
            id="64a7f0c2f1d2c4b5a6e7d902",
            icao="KJFK",
            iata="JFK",
            name="John F Kennedy International Airport",
            city="New York",
            country="United States",
            longitude=-73.778692,
            latitude=40.639928,
            created_at=base,
            updated_at=None,
        ),
    ]
