from fastapi import Depends

from app.repositories.dependencies import get_message_repository, get_todo_repository
from app.repositories.message import MessageRepository
from app.repositories.todo import TodoRepository
from app.services.message import MessageService
from app.services.todo import TodoService


def get_todo_service(
    repo: TodoRepository = Depends(get_todo_repository),
) -> TodoService:
    return TodoService(repo)


def get_message_service(
    repo: MessageRepository = Depends(get_message_repository),
) -> MessageService:
    return MessageService(repo)
