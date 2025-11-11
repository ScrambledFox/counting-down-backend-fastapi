from fastapi import HTTPException, status


class TodoBadRequestException(HTTPException):
    """400 Exception raised for bad requests related to todo items."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class TodoNotFoundException(HTTPException):
    """404 Exception raised when a todo item is not found."""

    def __init__(self, item_id: str | None = None):
        detail = f"Todo item '{item_id}' not found" if item_id else "Item not found"
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
