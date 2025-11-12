from datetime import UTC, datetime

import pytest

from app.core.time import utc_now
from app.schemas.v1.todo import Todo, TodoCreate, TodoUpdate
from app.services.todo import TodoService


class TestTodoRepository_Integration:
    """Integration tests for TodoService."""

    def _normalize_datetime(self, dt: datetime | None) -> datetime | None:
        """Normalize datetime to UTC timezone-aware for comparison."""
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Assume naive datetime is UTC
            return dt.replace(tzinfo=UTC)
        return dt

    def _assert_todo_equal(self, todo1: Todo, todo2: Todo, tolerance_seconds: float = 1.0):
        assert todo1.id == todo2.id
        assert todo1.title == todo2.title
        assert todo1.category == todo2.category
        assert todo1.completed is todo2.completed

        # Compare timestamps with tolerance
        if todo1.created_at and todo2.created_at:
            dt1 = self._normalize_datetime(todo1.created_at)
            dt2 = self._normalize_datetime(todo2.created_at)
            assert dt1 is not None and dt2 is not None
            time_diff = abs((dt1 - dt2).total_seconds())
            assert time_diff <= tolerance_seconds, (
                f"created_at differs by {time_diff}s (tolerance: {tolerance_seconds}s)"
            )
        else:
            assert todo1.created_at == todo2.created_at

        if todo1.updated_at and todo2.updated_at:
            dt1 = self._normalize_datetime(todo1.updated_at)
            dt2 = self._normalize_datetime(todo2.updated_at)
            assert dt1 is not None and dt2 is not None
            time_diff = abs((dt1 - dt2).total_seconds())
            assert time_diff <= tolerance_seconds, (
                f"updated_at differs by {time_diff}s (tolerance: {tolerance_seconds}s)"
            )
        else:
            assert todo1.updated_at == todo2.updated_at

    @pytest.mark.asyncio
    async def test_todo_lifecycle(
        self,
        todo_service_real: TodoService,
        sample_todo_create: TodoCreate,
        sample_todo_update: TodoUpdate,
    ):
        # Create a new todo
        now = utc_now()
        created_todo = await todo_service_real.create(sample_todo_create)

        assert created_todo is not None
        self._assert_todo_equal(
            created_todo,
            Todo(
                id=created_todo.id,
                title=sample_todo_create.title,
                category=sample_todo_create.category,
                completed=sample_todo_create.completed,
                created_at=now,
                updated_at=None,
            ),
        )

        # Retrieve the created todo
        id = created_todo.id
        assert id is not None

        fetched_todo = await todo_service_real.get_by_id(id)
        assert fetched_todo is not None
        self._assert_todo_equal(created_todo, fetched_todo)

        # Update the todo
        now = utc_now()
        updated_todo = await todo_service_real.update(id, sample_todo_update)
        assert updated_todo is not None
        self._assert_todo_equal(
            updated_todo,
            Todo(
                id=id,
                title="Updated Todo",
                category=sample_todo_create.category,
                completed=sample_todo_create.completed,
                created_at=created_todo.created_at,
                updated_at=now,
            ),
        )

        # Toggle completion status
        toggled_todo = await todo_service_real.toggle_completion(id)
        assert toggled_todo is not None
        assert toggled_todo.completed is not updated_todo.completed

        # Delete the todo
        delete_result = await todo_service_real.delete(id)
        assert delete_result is True

        # Verify deletion
        deleted_todo = await todo_service_real.get_by_id(id)
        assert deleted_todo is None
