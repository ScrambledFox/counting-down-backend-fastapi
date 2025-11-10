from fastapi import APIRouter

from . import together_list

router = APIRouter()
router.include_router(together_list.router)


@router.get("/hello", tags=["demo"])
def say_hello():
    return {"message": "Hello, World!"}
