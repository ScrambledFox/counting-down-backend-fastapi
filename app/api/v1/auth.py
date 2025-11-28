from typing import Annotated, Any

from fastapi import Depends

from app.api.routing import make_router
from app.core import logging
from app.schemas.v1.session import SessionResponse
from app.services.auth import AuthService

router = make_router()

_logger = logging.get_logger(__name__)


@router.post("/login", summary="Login User and Create Session")
async def login_user(
    access_key: str,
    auth_service: Annotated[AuthService, Depends()],
):
    return await auth_service.login_user(access_key)


@router.post("/logout", summary="Logout User and Invalidate Session")
async def logout_user(
    session_id: str,
    auth_service: Annotated[AuthService, Depends()],
) -> dict[str, Any]:
    result, detail = await auth_service.invalidate_session(session_id)
    return {"success": result, "session_id": session_id, "detail": detail}


@router.get("/session", summary="Get Current Session Info")
async def get_session_info(
    session_id: str,
    auth_service: Annotated[AuthService, Depends()],
) -> SessionResponse:
    return await auth_service.get_session_info(session_id)
