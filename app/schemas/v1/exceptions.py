from typing import Any

from fastapi import HTTPException, status


class BadRequestException(HTTPException):
    """400 Exception raised for bad requests related to todo items."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class UnauthorizedException(HTTPException):
    """401 Exception raised for unauthorized access."""

    def __init__(self, detail: str = "Unauthorized"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


class ForbiddenException(HTTPException):
    """403 Exception raised for forbidden access."""

    def __init__(self, detail: str = "Forbidden"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class NotFoundException(HTTPException):
    """404 Exception raised when a todo item is not found."""

    def __init__(self, type_name: str, item_id: Any | None = None):
        detail = f"'{type_name}' '{item_id}' not found" if item_id else "Item not found"
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
