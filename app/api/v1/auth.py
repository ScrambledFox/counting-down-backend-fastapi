from typing import Annotated, Any

from fastapi import Depends, Security

from app.api.routing import make_router
from app.core.auth import require_session
from app.schemas.v1.session import SessionResponse
from app.services.auth import AuthService

router = make_router()


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
    session_info: Annotated[SessionResponse, Security(require_session)],
) -> SessionResponse:
    return session_info
