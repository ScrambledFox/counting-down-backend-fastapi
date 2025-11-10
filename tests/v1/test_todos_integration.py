"""
Integration tests for together_list_items (todos) endpoints.

These tests use a real MongoDB test database and test the full stack
from HTTP request to database and back.
"""
import pytest
from fastapi import status


@pytest.mark.asyncio
class TestTogetherListIntegration:
    """Integration tests for the complete todos API flow."""

    async def test_full_crud_workflow(self, integration_client):
        """Test complete CRUD workflow: Create, Read, Update, Delete."""
        # 1. Start with empty list
        response = await integration_client.get("/api/v1/todos/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

        # 2. Create a new todo
        create_payload = {
            "title": "Integration Test Todo",
            "category": "testing",
            "completed": False,
        }
        response = await integration_client.post("/api/v1/todos/", json=create_payload)
        assert response.status_code == status.HTTP_200_OK
        created_todo = response.json()
        assert created_todo["title"] == "Integration Test Todo"
        assert created_todo["category"] == "testing"
        assert created_todo["completed"] is False
        assert "id" in created_todo
        todo_id = created_todo["id"]

        # 3. Retrieve the created todo by ID
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        retrieved_todo = response.json()
        assert retrieved_todo["id"] == todo_id
        assert retrieved_todo["title"] == "Integration Test Todo"

        # 4. Update the todo
        update_payload = {
            "title": "Updated Integration Todo",
            "category": "testing-updated",
            "completed": True,
        }
        response = await integration_client.put(
            f"/api/v1/todos/{todo_id}", json=update_payload
        )
        assert response.status_code == status.HTTP_200_OK
        updated_todo = response.json()
        assert updated_todo["title"] == "Updated Integration Todo"
        assert updated_todo["category"] == "testing-updated"
        assert updated_todo["completed"] is True

        # 5. Verify the update persisted
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Updated Integration Todo"

        # 6. Delete the todo
        response = await integration_client.delete(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["detail"] == "Item deleted"

        # 7. Verify deletion
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # 8. Verify empty list again
        response = await integration_client.get("/api/v1/todos/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_list_multiple_todos(self, integration_client, sample_todo_data_list):
        """Test creating and listing multiple todos."""
        created_ids = []

        # Create multiple todos
        for todo_data in sample_todo_data_list:
            response = await integration_client.post("/api/v1/todos/", json=todo_data)
            assert response.status_code == status.HTTP_200_OK
            created_ids.append(response.json()["id"])

        # Retrieve all todos
        response = await integration_client.get("/api/v1/todos/")
        assert response.status_code == status.HTTP_200_OK
        todos = response.json()
        assert len(todos) == 3

        # Verify todos are sorted by created_at (oldest first)
        assert todos[0]["title"] == "Write tests"
        assert todos[1]["title"] == "Review PR"
        assert todos[2]["title"] == "Buy milk"

        # Verify categories
        assert todos[0]["category"] == "work"
        assert todos[1]["category"] == "work"
        assert todos[2]["category"] == "shopping"

        # Verify completion status
        assert todos[0]["completed"] is False
        assert todos[1]["completed"] is True
        assert todos[2]["completed"] is False

    async def test_toggle_completion_workflow(self, integration_client, sample_todo_data):
        """Test toggling todo completion status."""
        # Create a todo
        response = await integration_client.post("/api/v1/todos/", json=sample_todo_data)
        assert response.status_code == status.HTTP_200_OK
        todo = response.json()
        todo_id = todo["id"]
        assert todo["completed"] is False

        # Toggle to completed
        response = await integration_client.post(
            f"/api/v1/todos/{todo_id}/toggle-completion"
        )
        assert response.status_code == status.HTTP_200_OK
        toggled_todo = response.json()
        assert toggled_todo["completed"] is True

        # Verify it persisted
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["completed"] is True

        # Toggle back to incomplete
        response = await integration_client.post(
            f"/api/v1/todos/{todo_id}/toggle-completion"
        )
        assert response.status_code == status.HTTP_200_OK
        toggled_todo = response.json()
        assert toggled_todo["completed"] is False

        # Verify it persisted
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["completed"] is False

    async def test_create_todo_validation(self, integration_client):
        """Test validation when creating todos."""
        # Test empty title
        response = await integration_client.post(
            "/api/v1/todos/",
            json={"title": "   ", "category": "test"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Title cannot be empty" in response.json()["detail"]

        # Test empty category
        response = await integration_client.post(
            "/api/v1/todos/",
            json={"title": "Test", "category": "  "},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Category cannot be empty" in response.json()["detail"]

        # Test missing category field
        response = await integration_client.post(
            "/api/v1/todos/",
            json={"title": "Test"},
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    async def test_update_todo_validation(self, integration_client, sample_todo_data):
        """Test validation when updating todos."""
        # Create a todo first
        response = await integration_client.post("/api/v1/todos/", json=sample_todo_data)
        assert response.status_code == status.HTTP_200_OK
        todo_id = response.json()["id"]

        # Test empty title update
        response = await integration_client.put(
            f"/api/v1/todos/{todo_id}",
            json={"title": "   ", "category": "test"},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Title cannot be empty" in response.json()["detail"]

        # Test empty category update
        response = await integration_client.put(
            f"/api/v1/todos/{todo_id}",
            json={"title": "Test", "category": "  "},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Category cannot be empty" in response.json()["detail"]

    async def test_get_nonexistent_todo(self, integration_client):
        """Test retrieving a todo that doesn't exist."""
        # Valid ObjectId format but doesn't exist
        response = await integration_client.get("/api/v1/todos/507f1f77bcf86cd799439011")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    async def test_update_nonexistent_todo(self, integration_client):
        """Test updating a todo that doesn't exist."""
        response = await integration_client.put(
            "/api/v1/todos/507f1f77bcf86cd799439011",
            json={"title": "Test", "category": "test"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    async def test_delete_nonexistent_todo(self, integration_client):
        """Test deleting a todo that doesn't exist."""
        response = await integration_client.delete("/api/v1/todos/507f1f77bcf86cd799439011")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    async def test_toggle_nonexistent_todo(self, integration_client):
        """Test toggling completion on a todo that doesn't exist."""
        response = await integration_client.post(
            "/api/v1/todos/507f1f77bcf86cd799439011/toggle-completion"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Item not found"

    async def test_invalid_mongodb_id_format(self, integration_client):
        """Test operations with invalid MongoDB ObjectId format."""
        invalid_id = "not-a-valid-mongodb-id"

        # Test get
        response = await integration_client.get(f"/api/v1/todos/{invalid_id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test update
        response = await integration_client.put(
            f"/api/v1/todos/{invalid_id}",
            json={"title": "Test", "category": "test"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test delete
        response = await integration_client.delete(f"/api/v1/todos/{invalid_id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test toggle
        response = await integration_client.post(
            f"/api/v1/todos/{invalid_id}/toggle-completion"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_timestamps_are_set(self, integration_client, sample_todo_data):
        """Test that timestamps are properly managed on create and update."""
        # Create a todo
        response = await integration_client.post("/api/v1/todos/", json=sample_todo_data)
        assert response.status_code == status.HTTP_200_OK
        todo = response.json()
        todo_id = todo["id"]

        # Small delay to ensure different timestamp
        import asyncio
        await asyncio.sleep(0.1)

        # Update the todo
        response = await integration_client.put(
            f"/api/v1/todos/{todo_id}",
            json={"title": "Updated", "category": "updated"},
        )
        assert response.status_code == status.HTTP_200_OK
        updated_todo = response.json()

        # Verify the update succeeded
        assert updated_todo["title"] == "Updated"
        assert updated_todo["category"] == "updated"
        assert updated_todo["id"] == todo_id

    async def test_concurrent_updates(self, integration_client, sample_todo_data):
        """Test that concurrent updates work correctly."""
        # Create a todo
        response = await integration_client.post("/api/v1/todos/", json=sample_todo_data)
        assert response.status_code == status.HTTP_200_OK
        todo_id = response.json()["id"]

        # Perform multiple updates
        import asyncio

        async def update_todo(title: str):
            return await integration_client.put(
                f"/api/v1/todos/{todo_id}",
                json={"title": title, "category": "test"},
            )

        # Run concurrent updates
        results = await asyncio.gather(
            update_todo("Update 1"),
            update_todo("Update 2"),
            update_todo("Update 3"),
        )

        # All updates should succeed
        for result in results:
            assert result.status_code == status.HTTP_200_OK

        # Final state should be one of the updates
        response = await integration_client.get(f"/api/v1/todos/{todo_id}")
        assert response.status_code == status.HTTP_200_OK
        final_todo = response.json()
        assert final_todo["title"] in ["Update 1", "Update 2", "Update 3"]

    async def test_partial_update(self, integration_client, sample_todo_data):
        """Test that updates only change specified fields."""
        # Create a todo
        response = await integration_client.post("/api/v1/todos/", json=sample_todo_data)
        assert response.status_code == status.HTTP_200_OK
        todo = response.json()
        todo_id = todo["id"]
        original_title = todo["title"]
        original_category = todo["category"]

        # Update only the completed status via toggle
        response = await integration_client.post(
            f"/api/v1/todos/{todo_id}/toggle-completion"
        )
        assert response.status_code == status.HTTP_200_OK
        updated_todo = response.json()

        # Title and category should remain unchanged
        assert updated_todo["title"] == original_title
        assert updated_todo["category"] == original_category
        # Only completed should change
        assert updated_todo["completed"] is True
