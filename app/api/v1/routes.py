from fastapi import APIRouter

from . import airport, flight, message, todo

router = APIRouter()

router.include_router(todo.router)
router.include_router(message.router)
router.include_router(flight.router)
router.include_router(airport.router)
