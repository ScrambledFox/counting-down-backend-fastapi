from typing import Annotated, Any

from fastapi import Depends, Header, Response, Security

from app.api.routing import make_router
from app.core.auth import require_session
from app.core.config import get_settings
from app.schemas.v1.session import LoginRequest, SessionResponse
from app.services.auth import AuthService

router = make_router()

settings = get_settings()

SESSION_COOKIE_NAME = "session_id"


@router.post("/login", summary="Login User and Create Session")
async def login_user(
    body: LoginRequest,
    response: Response,
    auth_service: Annotated[AuthService, Depends()],
) -> SessionResponse:
    session = await auth_service.login_user(body.access_key)
    is_prod = settings.app_env.lower() == "prod"
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.session_id,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=settings.session_duration,
    )
    return session


@router.post("/logout", summary="Logout User and Invalidate Session")
async def logout_user(
    response: Response,
    auth_service: Annotated[AuthService, Depends()],
    x_session_id: str = Header(...),
) -> dict[str, Any]:
    result, detail = await auth_service.invalidate_session(x_session_id)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return {"success": result, "session_id": x_session_id, "detail": detail}


@router.get("/session", summary="Get Current Session Info")
async def get_session_info(
    session_info: Annotated[SessionResponse, Security(require_session)],
) -> SessionResponse:
    return session_info
