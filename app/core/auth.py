from typing import Annotated

from fastapi import Cookie, Depends, Security
from fastapi.security import APIKeyHeader

from app.core import logging
from app.schemas.v1.exceptions import UnauthorizedException
from app.schemas.v1.session import SessionResponse
from app.services.auth import AuthService

session_id_header = APIKeyHeader(name="X-Session-Id", auto_error=False)

logger = logging.get_logger(__name__)


async def require_session(
    auth_service: Annotated[AuthService, Depends()],
    x_session_id: str | None = Security(session_id_header),
    session_cookie_id: str | None = Cookie(default=None, alias="session_id"),
) -> SessionResponse:
    """Dependency to require a valid session.

    Accepts the session ID from the HttpOnly cookie (preferred) or the
    X-Session-Id request header. Raises UnauthorizedException if neither
    is present or the session is invalid/expired.

    Returns:
        SessionResponse: Info about the current session and authenticated user.
         - session_id: str
         - user_type: UserType
         - created_at: datetime
         - expires_at: datetime
    """
    sid = session_cookie_id or x_session_id
    if not sid:
        raise UnauthorizedException("No session provided")
    try:
        return await auth_service.get_session_info(sid)
    except Exception as e:
        logger.warning("Unauthorized access attempt")
        raise UnauthorizedException("Invalid or expired session") from e
