from fastapi import APIRouter

from app.api.routing import NoAliasAPIRoute

from . import airport, flight, message, todo

router = APIRouter(route_class=NoAliasAPIRoute)

router.include_router(todo.router)
router.include_router(message.router)
router.include_router(flight.router)
router.include_router(airport.router)
