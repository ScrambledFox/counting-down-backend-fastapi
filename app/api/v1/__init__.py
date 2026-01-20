from fastapi import APIRouter

from app.api.routing import NoAliasAPIRoute
from app.api.v1 import advent, airport, auth, flight, image, message, todo

router = APIRouter(prefix="/v1", route_class=NoAliasAPIRoute)

router.include_router(todo.router, prefix="/todos", tags=["todos"])
router.include_router(message.router, prefix="/messages", tags=["messages"])
router.include_router(flight.router, prefix="/flights", tags=["flights"])
router.include_router(airport.router, prefix="/airports", tags=["airports"])
router.include_router(image.router, tags=["images"])
router.include_router(advent.router, prefix="/advent", tags=["advent"])
router.include_router(auth.router, tags=["login"])
