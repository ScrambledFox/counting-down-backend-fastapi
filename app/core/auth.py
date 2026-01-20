from typing import Annotated

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

from app.schemas.v1.exceptions import UnauthorizedException
from app.schemas.v1.session import SessionResponse
from app.services.auth import AuthService

session_id_header = APIKeyHeader(name="X-Session-Id", auto_error=False)


async def require_session(
    auth_service: Annotated[AuthService, Depends()],
    x_session_id: str = Security(session_id_header),
) -> SessionResponse:
    """Dependency to require a valid session.

    Raises:
        UnauthorizedException

    Returns:
        SessionResponse: Info about the current session and authenticated user.
         - session_id: str
         - user_type: UserType
         - created_at: datetime
         - expires_at: datetime
    """
    try:
        return await auth_service.get_session_info(x_session_id)
    except Exception as e:
        raise UnauthorizedException("Invalid or expired session") from e
