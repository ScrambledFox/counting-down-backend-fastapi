from typing import Annotated

from fastapi import Depends, Header

from app.schemas.v1.exceptions import UnauthorizedException
from app.schemas.v1.session import SessionResponse
from app.services.auth import AuthService


async def require_session(
    auth_service: Annotated[AuthService, Depends()],
    x_session_id: str = Header(alias="X-Session-Id"),
) -> SessionResponse:
    try:
        return await auth_service.get_session_info(x_session_id)
    except Exception as e:
        raise UnauthorizedException("Invalid or expired session") from e
