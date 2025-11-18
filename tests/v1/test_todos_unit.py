import datetime
from datetime import datetime as dt
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from app.api.v1.todo import create_todo_item, get_todo_item
from app.schemas.v1.exceptions import NotFoundException
from app.schemas.v1.todo import Todo, TodoCreate
from app.services.todo import TodoService


class TestTodoRoutes_Get:
    """Unit tests for Todo API routes."""

    @pytest.mark.asyncio
    async def test_get_todo_item_success(self):
        """Test successfully retrieving a todo item by ID."""
        # Arrange
        item_id = "64a7f0c2f1d2c4b5a6e7d8f1"
        expected_todo = Todo(
            id=item_id,
            title="Test Todo",
            category="Work",
            completed=False,
            created_at=dt.fromisoformat("2023-01-01T12:00:00Z"),
            updated_at=None,
        )

        mock_service = Mock(spec=TodoService)
        mock_service.get_by_id = AsyncMock(return_value=expected_todo)

        # Act
        result = await get_todo_item(item_id=item_id, service=mock_service)

        # Assert
        assert result == expected_todo
        assert result.id == item_id
        assert result.title == "Test Todo"
        mock_service.get_by_id.assert_called_once_with(item_id)

    @pytest.mark.asyncio
    async def test_get_todo_item_not_found(self):
        """Test retrieving a non-existent todo item raises NotFoundException."""
        # Arrange
        item_id = "nonexistent_id"

        mock_service = Mock(spec=TodoService)
        mock_service.get_by_id = AsyncMock(return_value=None)

        # Act & Assert
        with pytest.raises(NotFoundException) as exc_info:
            await get_todo_item(item_id=item_id, service=mock_service)

        assert item_id in str(exc_info.value)
        mock_service.get_by_id.assert_called_once_with(item_id)

    @pytest.mark.asyncio
    async def test_get_todo_item_service_raises_exception(self):
        """Test that exceptions from the service layer are propagated."""
        # Arrange
        item_id = "64a7f0c2f1d2c4b5a6e7d8f1"

        mock_service = Mock(spec=TodoService)
        mock_service.get_by_id = AsyncMock(side_effect=Exception("Database error"))

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await get_todo_item(item_id=item_id, service=mock_service)

        assert str(exc_info.value) == "Database error"
        mock_service.get_by_id.assert_called_once_with(item_id)

    @pytest.mark.asyncio
    async def test_get_todo_item_completed_status(self):
        """Test retrieving todo items with different completion statuses."""
        # Arrange
        item_id = "64a7f0c2f1d2c4b5a6e7d8f1"

        for completed_status in [True, False]:
            expected_todo = Todo(
                id=item_id,
                title="Test Todo",
                category="Work",
                completed=completed_status,
                created_at=dt.fromisoformat("2023-01-01T12:00:00Z"),
                updated_at=None,
            )

            mock_service = Mock(spec=TodoService)
            mock_service.get_by_id = AsyncMock(return_value=expected_todo)

            # Act
            result = await get_todo_item(item_id=item_id, service=mock_service)

            # Assert
            assert result.completed == completed_status
            mock_service.get_by_id.assert_called_once_with(item_id)


class TestTodoRoutes_Create:
    """Unit tests for Todo API create route."""

    @pytest.mark.asyncio
    async def test_create_todo_item_success(self):
        """Test successfully creating a todo item."""
        # Arrange
        todo_create = TodoCreate(
            title="New Todo",
            category="Personal",
            completed=False,
        )

        expected_todo = Todo(
            id="64a7f0c2f1d2c4b5a6e7d8f3",
            title="New Todo",
            category="Personal",
            completed=False,
            created_at=dt.fromisoformat("2023-01-01T12:00:00Z"),
            updated_at=None,
        )

        mock_service = Mock(spec=TodoService)
        mock_service.create = AsyncMock(return_value=expected_todo)

        # Act
        from app.api.v1.todo import create_todo_item

        result = await create_todo_item(item=todo_create, service=mock_service)

        # Assert
        assert result == expected_todo
        assert result.title == "New Todo"
        mock_service.create.assert_called_once_with(todo_create)

    @pytest.mark.asyncio
    async def test_create_todo_item_invalid_data(self):
        """Test creating a todo item with invalid data raises ValidationError."""
        # Act & Assert
        with pytest.raises(ValidationError) as exc_info:
            invalid_todo_create = TodoCreate(
                title="",
                category="",
                completed=False,
            )

            mock_service = Mock(spec=TodoService)

            await create_todo_item(item=invalid_todo_create, service=mock_service)

            assert "value_error" in str(exc_info.value)
            mock_service.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_todo_item_service_raises_exception(self):
        """Test that exceptions from the service layer are propagated during creation."""
        # Arrange
        todo_create = TodoCreate(
            title="New Todo",
            category="Personal",
            completed=False,
        )

        mock_service = Mock(spec=TodoService)
        mock_service.create = AsyncMock(side_effect=Exception("Database error on create"))

        # Act & Assert
        from app.api.v1.todo import create_todo_item

        with pytest.raises(Exception) as exc_info:
            await create_todo_item(item=todo_create, service=mock_service)

        assert str(exc_info.value) == "Database error on create"
        mock_service.create.assert_called_once_with(todo_create)

    @pytest.mark.asyncio
    async def test_create_todo_item_trims_whitespace(self):
        """Test that leading/trailing whitespace in title and category is trimmed."""
        # Arrange
        todo_create = TodoCreate(
            title="   Trimmed Title   ",
            category="   Trimmed Category   ",
            completed=False,
        )

        expected_todo = Todo(
            id="64a7f0c2f1d2c4b5a6e7d8f4",
            title="Trimmed Title",
            category="Trimmed Category",
            completed=False,
            created_at=dt.fromisoformat("2023-01-01T12:00:00Z"),
            updated_at=None,
        )

        mock_service = Mock(spec=TodoService)
        mock_service.create = AsyncMock(return_value=expected_todo)

        # Act
        from app.api.v1.todo import create_todo_item

        result = await create_todo_item(item=todo_create, service=mock_service)

        # Assert
        assert result.title == "Trimmed Title"
        assert result.category == "Trimmed Category"
        mock_service.create.assert_called_once_with(todo_create)


class TestTodoRepository:
    """Unit tests for TodoService."""

    @pytest.mark.asyncio
    async def test_get_empty_todo_list(self, todo_service_mock: TodoService):
        todos = await todo_service_mock.get_all()
        assert len(todos) == 0

    @pytest.mark.asyncio
    async def test_get_todos_list(
        self,
        todo_service_mock: TodoService,
        todo_repository_mock: Mock,
        sample_todos: list[Todo],
    ):
        todo_repository_mock.list_todos.return_value = sample_todos

        todos = await todo_service_mock.get_all()
        assert len(todos) == 2
        assert todos[0].title == sample_todos[0].title
        assert todos[1].completed is sample_todos[1].completed

    @pytest.mark.asyncio
    async def test_get_list_raises_exception(
        self, todo_service_mock: TodoService, todo_repository_mock: Mock
    ):
        todo_repository_mock.list_todos.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await todo_service_mock.get_all()
        assert str(exc_info.value) == "Database error"

    @pytest.mark.asyncio
    async def test_get_todo_by_id(
        self,
        todo_service_mock: TodoService,
        todo_repository_mock: Mock,
        sample_todos: list[Todo],
    ):
        todo_repository_mock.get_todo.return_value = sample_todos[0]

        todo = await todo_service_mock.get_by_id("64a7f0c2f1d2c4b5a6e7d8f1")
        assert todo is not None
        assert todo.id == sample_todos[0].id
        assert todo.title == sample_todos[0].title

    @pytest.mark.asyncio
    async def test_get_todo_by_id_not_found(
        self, todo_service_mock: TodoService, todo_repository_mock: Mock
    ):
        todo_repository_mock.get_todo.return_value = None

        todo = await todo_service_mock.get_by_id("nonexistent_id")
        assert todo is None

    @pytest.mark.asyncio
    async def test_get_todo_by_id_raises_exception(
        self, todo_service_mock: TodoService, todo_repository_mock: Mock
    ):
        todo_repository_mock.get_todo.side_effect = Exception("Database error")

        with pytest.raises(Exception) as exc_info:
            await todo_service_mock.get_by_id("some_id")
        assert str(exc_info.value) == "Database error"

    @pytest.mark.asyncio
    async def test_create_todo_success(
        self,
        todo_service_mock: TodoService,
        todo_repository_mock: Mock,
        sample_todo_create: TodoCreate,
    ):
        fixed_now = datetime.datetime(2023, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
        mock_id = "64a7f0c2f1d2c4b5a6e7d8f3"

        with patch("app.services.todo.utc_now", return_value=fixed_now):
            todo_repository_mock.create_todo.return_value = Todo(
                id=mock_id,
                title=sample_todo_create.title,
                category=sample_todo_create.category,
                completed=sample_todo_create.completed,
                created_at=fixed_now,
                updated_at=None,
            )
            todo_repository_mock.get_todo.return_value = Todo(
                id=mock_id,
                title=sample_todo_create.title,
                category=sample_todo_create.category,
                completed=sample_todo_create.completed,
                created_at=fixed_now,
                updated_at=None,
            )

            created_todo = await todo_service_mock.create(sample_todo_create)

            assert created_todo is not None
            assert created_todo.id == mock_id
            assert created_todo.title == sample_todo_create.title
            assert created_todo.category == sample_todo_create.category
            assert created_todo.completed is sample_todo_create.completed
            assert created_todo.created_at == fixed_now
            assert created_todo.updated_at is None

            todo_repository_mock.create_todo.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_todo_invalid_data(
        self,
        todo_service_mock: TodoService,
        todo_repository_mock: Mock,
    ):
        with pytest.raises(ValidationError) as exc_info:
            invalid_todo_create = TodoCreate(
                title="",
                category="",
                completed=False,
            )

            await todo_service_mock.create(invalid_todo_create)
        assert "value_error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_create_todo_raises_exception(
        self,
        todo_service_mock: TodoService,
        todo_repository_mock: Mock,
        sample_todo_create: TodoCreate,
    ):
        todo_repository_mock.create_todo.side_effect = Exception("Database error on create")

        with pytest.raises(Exception) as exc_info:
            await todo_service_mock.create(sample_todo_create)
        assert str(exc_info.value) == "Database error on create"
