from fastapi import APIRouter

from . import todo

router = APIRouter()
router.include_router(todo.router)


@router.get("/hello", tags=["demo"])
def say_hello():
    return {"message": "Hello, World!"}
