from fastapi import APIRouter

from . import todos

router = APIRouter()
router.include_router(todos.router)


@router.get("/hello", tags=["demo"])
def say_hello():
    return {"message": "Hello, World!"}
