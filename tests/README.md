# Test Suite Documentation

This document describes the test suite for the Counting Down FastAPI backend.

## Test Structure

The test suite is organized into two main categories:

### 1. Unit Tests (`test_todos.py`)
Unit tests use mocked services to test individual components in isolation.

**Test Coverage (21 tests):**

- **GET `/api/v1/todos/`** - List all todos
  - Empty list scenario
  - Multiple items retrieval

- **POST `/api/v1/todos/`** - Create a new todo
  - Successful creation
  - Empty title validation
  - Empty category validation  
  - Missing required fields
  - Default completed value

- **GET `/api/v1/todos/{item_id}`** - Get a single todo
  - Successful retrieval by ID
  - Item not found (404)
  - Invalid ID format

- **PUT `/api/v1/todos/{item_id}`** - Update a todo
  - Successful update
  - Item not found (404)
  - Empty title validation
  - Empty category validation

- **DELETE `/api/v1/todos/{item_id}`** - Delete a todo
  - Successful deletion
  - Item not found (404)
  - Invalid ID format

- **POST `/api/v1/todos/{item_id}/toggle-completion`** - Toggle completion status
  - Toggle to completed
  - Toggle to incomplete
  - Item not found (404)
  - Invalid ID format

### 2. Integration Tests (`test_todos_integration.py`)
Integration tests use a real MongoDB test database and test the full stack from HTTP request to database and back.

**Test Coverage (13 tests):**

- **Full CRUD workflow** - Complete create, read, update, delete cycle
- **List multiple todos** - Creating and retrieving multiple items
- **Toggle completion workflow** - Testing completion status toggling with persistence
- **Create todo validation** - Empty title, empty category, missing fields
- **Update todo validation** - Empty title, empty category validation
- **Error handling** - Testing 404 responses for non-existent items
- **Invalid MongoDB ID format** - Testing all operations with invalid IDs
- **Timestamp management** - Verifying create/update timestamp behavior
- **Concurrent updates** - Testing that multiple simultaneous updates work correctly
- **Partial updates** - Verifying that updates only change specified fields

## Running Tests

### Run All Tests
```bash
uv run pytest
```

### Run Only Unit Tests
```bash
uv run pytest tests/v1/test_todos.py -v
```

### Run Only Integration Tests
```bash
uv run pytest tests/v1/test_todos_integration.py -v
```

### Run with Coverage
```bash
uv run pytest --cov=app --cov-report=html
```

### Run Specific Test
```bash
uv run pytest tests/v1/test_todos.py::TestCreateTogetherListItem::test_create_item_success -v
```

## Test Fixtures

### Unit Test Fixtures (`conftest.py`)

- `mock_db` - Mock MongoDB database
- `mock_repository` - Mock TogetherListRepository
- `mock_service` - Mock TogetherListService
- `client` - FastAPI TestClient with mocked dependencies
- `sample_todo_item` - Sample todo item data for reuse
- `sample_todo_items` - Multiple sample todo items

### Integration Test Fixtures (`conftest.py`)

- `test_db_name` - Name of the test database (session-scoped)
- `test_db` - Real MongoDB test database connection (function-scoped, auto-cleanup)
- `integration_client` - AsyncClient configured with test database
- `sample_todo_data` - Sample todo creation data
- `sample_todo_data_list` - Multiple sample todo items for bulk operations

## Database Setup for Integration Tests

Integration tests require a MongoDB instance. The tests will:

1. Create a temporary test database (appends `_test` to configured database name)
2. Run the test
3. Automatically drop the test database after each test

**Requirements:**
- MongoDB instance must be running and accessible
- `MONGO_URL` environment variable must be set (via `.env` file)
- Test database name is derived from `MONGO_DB_NAME` setting

**Example `.env` configuration:**
```env
MONGO_URL=mongodb://localhost:27017
MONGO_DB_NAME=counting_down
TOGETHER_LIST_COLLECTION_NAME=together_list_items
```

The integration tests will use `counting_down_test` as the database name.

## Test Patterns

### Unit Tests
Unit tests follow the Arrange-Act-Assert (AAA) pattern:

```python
async def test_example(self, client, mock_service):
    # Arrange: Set up mocks
    mock_service.method = AsyncMock(return_value=expected_data)
    
    # Act: Make the request
    response = client.get("/endpoint")
    
    # Assert: Verify the response
    assert response.status_code == 200
    assert response.json() == expected_data
```

### Integration Tests
Integration tests verify end-to-end functionality:

```python
async def test_full_workflow(self, integration_client):
    # Create
    response = await integration_client.post("/api/v1/todos/", json=data)
    item_id = response.json()["id"]
    
    # Read
    response = await integration_client.get(f"/api/v1/todos/{item_id}")
    assert response.status_code == 200
    
    # Update
    response = await integration_client.put(f"/api/v1/todos/{item_id}", json=updated_data)
    
    # Delete
    response = await integration_client.delete(f"/api/v1/todos/{item_id}")
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. Ensure:

1. MongoDB service is available
2. Environment variables are configured
3. All dependencies are installed via `uv sync`

## Test Statistics

- **Total Tests:** 35 (22 unit + 13 integration)
- **Code Coverage:** Run with `--cov` flag to generate coverage report
- **Average Execution Time:** ~8 seconds (including database operations)

## Adding New Tests

When adding new endpoints or features:

1. **Add unit tests** in `test_todos.py` for:
   - Success cases
   - Validation errors
   - Edge cases
   - Error handling

2. **Add integration tests** in `test_todos_integration.py` for:
   - Full workflows
   - Database persistence
   - Real-world scenarios
   - Cross-endpoint interactions

3. **Update this documentation** with new test descriptions
