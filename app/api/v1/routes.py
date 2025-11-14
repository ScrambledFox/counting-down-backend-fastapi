from fastapi import APIRouter

from app.api.routing import NoAliasAPIRoute

from . import airport, flight, message, todo

router = APIRouter(route_class=NoAliasAPIRoute)

router.include_router(todo.router, prefix="/todos", tags=["todos"])
router.include_router(message.router, prefix="/messages", tags=["messages"])
router.include_router(flight.router, prefix="/flights", tags=["flights"])
router.include_router(airport.router, prefix="/airports", tags=["airports"])
