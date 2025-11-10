"""Unit tests for todo_items (todos) endpoints."""
from unittest.mock import AsyncMock

import pytest
from fastapi import status


class TestGetTodoItems:
    """Tests for GET /api/v1/todos/"""

    @pytest.mark.asyncio
    async def test_get_all_items_empty_list(self, client, mock_service):
        """Test retrieving todos when list is empty."""
        mock_service.get_all_items = AsyncMock(return_value=[])
        
        response = client.get("/api/v1/todos/")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_all_items_with_data(self, client, mock_service, sample_todo_items):
        """Test retrieving multiple todos."""
        mock_service.get_all_items = AsyncMock(return_value=sample_todo_items)
        
        response = client.get("/api/v1/todos/")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 3
        assert data[0]["title"] == "First Todo"
        assert data[1]["title"] == "Second Todo"
        assert data[2]["title"] == "Third Todo"


class TestCreateTodoItem:
    """Tests for POST /api/v1/todos/"""

    @pytest.mark.asyncio
    async def test_create_item_success(self, client, mock_service, sample_todo_item):
        """Test successfully creating a new todo item."""
        mock_service.create_item = AsyncMock(return_value=sample_todo_item)
        
        payload = {
            "title": "Test Todo",
            "category": "personal",
            "completed": False,
        }
        
        response = client.post("/api/v1/todos/", json=payload)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["title"] == "Test Todo"
        assert data["category"] == "personal"
        assert data["completed"] is False
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_item_empty_title(self, client, mock_service):
        """Test creating item with empty title returns validation error."""
        mock_service.create_item = AsyncMock(
            side_effect=ValueError("Title cannot be empty")
        )
        
        payload = {
            "title": "   ",
            "category": "personal",
        }
        
        response = client.post("/api/v1/todos/", json=payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Title cannot be empty" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_item_empty_category(self, client, mock_service):
        """Test creating item with empty category returns validation error."""
        mock_service.create_item = AsyncMock(
            side_effect=ValueError("Category cannot be empty")
        )
        
        payload = {
            "title": "Test Todo",
            "category": "  ",
        }
        
        response = client.post("/api/v1/todos/", json=payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Category cannot be empty" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_item_missing_fields(self, client):
        """Test creating item with missing required fields."""
        payload = {
            "title": "Test Todo",
            # Missing category
        }
        
        response = client.post("/api/v1/todos/", json=payload)
        
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_create_item_default_completed_false(
        self, client, mock_service, sample_todo_item
    ):
        """Test that completed defaults to False when not provided."""
        mock_service.create_item = AsyncMock(return_value=sample_todo_item)
        
        payload = {
            "title": "Test Todo",
            "category": "personal",
            # completed not provided
        }
        
        response = client.post("/api/v1/todos/", json=payload)
        
        assert response.status_code == status.HTTP_200_OK
        # Verify service was called with completed=False
        call_args = mock_service.create_item.call_args[0][0]
        assert "completed" in call_args


class TestGetTodoItem:
    """Tests for GET /api/v1/todos/{item_id}"""

    @pytest.mark.asyncio
    async def test_get_item_by_id_success(self, client, mock_service, sample_todo_item):
        """Test successfully retrieving a todo by ID."""
        mock_service.get_item_by_id = AsyncMock(return_value=sample_todo_item)
        
        response = client.get(f"/api/v1/todos/{sample_todo_item['id']}")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == sample_todo_item["id"]
        assert data["title"] == sample_todo_item["title"]

    @pytest.mark.asyncio
    async def test_get_item_by_id_not_found(self, client, mock_service):
        """Test retrieving non-existent todo returns 404."""
        mock_service.get_item_by_id = AsyncMock(return_value=None)
        
        response = client.get("/api/v1/todos/507f1f77bcf86cd799439011")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    @pytest.mark.asyncio
    async def test_get_item_invalid_id_format(self, client, mock_service):
        """Test retrieving todo with invalid ID format."""
        mock_service.get_item_by_id = AsyncMock(return_value=None)
        
        response = client.get("/api/v1/todos/invalid_id")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateTodoItem:
    """Tests for PUT /api/v1/todos/{item_id}"""

    @pytest.mark.asyncio
    async def test_update_item_success(self, client, mock_service):
        """Test successfully updating a todo item."""
        updated_item = {
            "id": "507f1f77bcf86cd799439011",
            "title": "Updated Title",
            "category": "work",
            "completed": True,
            "created_at": "2025-11-10T10:00:00Z",
            "updated_at": "2025-11-10T15:00:00Z",
        }
        mock_service.update_item = AsyncMock(return_value=updated_item)
        
        payload = {
            "title": "Updated Title",
            "category": "work",
            "completed": True,
        }
        
        response = client.put("/api/v1/todos/507f1f77bcf86cd799439011", json=payload)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["category"] == "work"
        assert data["completed"] is True

    @pytest.mark.asyncio
    async def test_update_item_not_found(self, client, mock_service):
        """Test updating non-existent todo returns 404."""
        mock_service.update_item = AsyncMock(return_value=None)
        
        payload = {
            "title": "Updated Title",
            "category": "work",
        }
        
        response = client.put("/api/v1/todos/507f1f77bcf86cd799439011", json=payload)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    @pytest.mark.asyncio
    async def test_update_item_empty_title(self, client, mock_service):
        """Test updating with empty title returns validation error."""
        mock_service.update_item = AsyncMock(
            side_effect=ValueError("Title cannot be empty")
        )
        
        payload = {
            "title": "  ",
            "category": "work",
        }
        
        response = client.put("/api/v1/todos/507f1f77bcf86cd799439011", json=payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Title cannot be empty" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_update_item_empty_category(self, client, mock_service):
        """Test updating with empty category returns validation error."""
        mock_service.update_item = AsyncMock(
            side_effect=ValueError("Category cannot be empty")
        )
        
        payload = {
            "title": "Test",
            "category": "  ",
        }
        
        response = client.put("/api/v1/todos/507f1f77bcf86cd799439011", json=payload)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Category cannot be empty" in response.json()["detail"]


class TestDeleteTodoItem:
    """Tests for DELETE /api/v1/todos/{item_id}"""

    @pytest.mark.asyncio
    async def test_delete_item_success(self, client, mock_service):
        """Test successfully deleting a todo item."""
        mock_service.delete_item = AsyncMock(return_value=True)
        
        response = client.delete("/api/v1/todos/507f1f77bcf86cd799439011")
        
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["detail"] == "Item deleted"

    @pytest.mark.asyncio
    async def test_delete_item_not_found(self, client, mock_service):
        """Test deleting non-existent todo returns 404."""
        mock_service.delete_item = AsyncMock(return_value=False)
        
        response = client.delete("/api/v1/todos/507f1f77bcf86cd799439011")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    @pytest.mark.asyncio
    async def test_delete_item_invalid_id(self, client, mock_service):
        """Test deleting with invalid ID format."""
        mock_service.delete_item = AsyncMock(return_value=False)
        
        response = client.delete("/api/v1/todos/invalid_id")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestToggleTodoItemCompletion:
    """Tests for POST /api/v1/todos/{item_id}/toggle-completion"""

    @pytest.mark.asyncio
    async def test_toggle_completion_to_completed(self, client, mock_service):
        """Test toggling todo from incomplete to completed."""
        toggled_item = {
            "id": "507f1f77bcf86cd799439011",
            "title": "Test Todo",
            "category": "personal",
            "completed": True,
            "created_at": "2025-11-10T10:00:00Z",
            "updated_at": "2025-11-10T15:00:00Z",
        }
        mock_service.toggle_item_completion = AsyncMock(return_value=toggled_item)
        
        response = client.post("/api/v1/todos/507f1f77bcf86cd799439011/toggle-completion")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["completed"] is True

    @pytest.mark.asyncio
    async def test_toggle_completion_to_incomplete(self, client, mock_service):
        """Test toggling todo from completed to incomplete."""
        toggled_item = {
            "id": "507f1f77bcf86cd799439011",
            "title": "Test Todo",
            "category": "personal",
            "completed": False,
            "created_at": "2025-11-10T10:00:00Z",
            "updated_at": "2025-11-10T15:00:00Z",
        }
        mock_service.toggle_item_completion = AsyncMock(return_value=toggled_item)
        
        response = client.post("/api/v1/todos/507f1f77bcf86cd799439011/toggle-completion")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["completed"] is False

    @pytest.mark.asyncio
    async def test_toggle_completion_not_found(self, client, mock_service):
        """Test toggling completion on non-existent todo returns 404."""
        mock_service.toggle_item_completion = AsyncMock(return_value=None)
        
        response = client.post("/api/v1/todos/507f1f77bcf86cd799439011/toggle-completion")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    @pytest.mark.asyncio
    async def test_toggle_completion_invalid_id(self, client, mock_service):
        """Test toggling completion with invalid ID format."""
        mock_service.toggle_item_completion = AsyncMock(return_value=None)
        
        response = client.post("/api/v1/todos/invalid_id/toggle-completion")
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
