from datetime import UTC, datetime

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.routing import NoAliasAPIRoute
from app.schemas.v1.todo import Todo


@pytest.mark.asyncio
async def test_todo_serialization_uses_id_not__id():
    """Ensure HTTP layer outputs `id` not `_id` when using NoAliasAPIRoute."""
    app = FastAPI()

    router = APIRouter(prefix="/todos", route_class=NoAliasAPIRoute)

    @router.get("/", response_model=list[Todo])
    async def list_todos():  # pragma: no cover - fixture route
        # Construct via alias to prove parsing works while serialization omits alias.
        return [
            Todo.model_validate(
                {
                    "_id": "64a7f0c2f1d2c4b5a6e7d8f1",
                    "title": "Test",
                    "category": "Cat",
                    "completed": False,
                    "created_at": datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
                    "updated_at": None,
                }
            )
        ]

    # Reference the handler so static analyzers/linters consider it used.
    assert callable(list_todos)

    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    resp = client.get("/api/v1/todos/")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["id"] == "64a7f0c2f1d2c4b5a6e7d8f1"
    assert "_id" not in item
