from datetime import timedelta
from typing import Annotated

from fastapi import Depends

from app.core import logging
from app.core.config import get_settings
from app.repositories.session import SessionRepository
from app.schemas.v1.exceptions import ForbiddenException, NotFoundException
from app.schemas.v1.session import Session, SessionResponse
from app.schemas.v1.user import UserType
from app.services.user import UserService
from app.util.crypto import generate_session_id
from app.util.time import utc_now

settings = get_settings()


class AuthService:
    def __init__(
        self,
        session_repo: Annotated[SessionRepository, Depends()],
        user_service: Annotated[UserService, Depends()],
    ) -> None:
        self._logger = logging.get_logger(__name__)
        self._sessions = session_repo
        self._user_service = user_service

    def _get_user_by_access_key(self, access_key: str) -> UserType | None:
        valid_keys: dict[str, UserType] = {}
        if settings.access_key_danfeng:
            valid_keys[settings.access_key_danfeng] = UserType.DANFENG
        if settings.access_key_joris:
            valid_keys[settings.access_key_joris] = UserType.JORIS
        return valid_keys.get(access_key)

    def _session_response_from_session(self, session: Session) -> SessionResponse:
        return SessionResponse(
            session_id=str(session.session_id),
            user_type=session.user_type,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )

    async def is_valid_session(self, session_id: str) -> bool:
        self._logger.info(f"Validating session: {session_id}")
        await self._sessions.delete_expired_sessions()
        session = await self._sessions.get_session_by_id(session_id)
        if not session:
            raise NotFoundException("Session does not exist or is expired")
        return True

    async def get_session_info(self, session_id: str) -> SessionResponse:
        self._logger.info(f"Fetching session info for: {session_id}")
        await self._sessions.delete_expired_sessions()
        session = await self._sessions.get_session_by_id(session_id)
        if not session:
            raise NotFoundException("Session does not exist or is expired")
        return self._session_response_from_session(session)

    async def invalidate_session(self, session_id: str) -> tuple[bool, str]:
        session = await self._sessions.get_session_by_id(session_id)
        if not session:
            self._logger.warning(
                f"Attempt to invalidate non-existent or expired session: {session_id}"
            )
            return False, "Session does not exist or is already expired"

        result = await self._sessions.invalidate_session_with_id(session_id)
        if result > 0:
            self._logger.info(f"Session invalidated: {session_id}")
            return True, "Session successfully invalidated"
        else:
            self._logger.warning(f"Failed to invalidate session: {session_id}")
            return False, "Failed to invalidate session"

    async def invalidate_all_sessions(self) -> int:
        return await self._sessions.invalidate_all_sessions()

    async def count_active_sessions(self) -> int:
        return await self._sessions.count_active_sessions()

    async def login_user(self, access_key: str) -> SessionResponse:
        self._logger.info("Deleting expired sessions before login")
        await self._sessions.delete_expired_sessions()

        self._logger.info("Login attempt with access key")

        # Validate access key and get user type
        user_type = self._get_user_by_access_key(access_key)
        if user_type is None:
            self._logger.warning("Invalid access key attempt")
            raise ForbiddenException("Invalid access key")

        # Get user details
        user = self._user_service.get_user_from_user_type(user_type)

        # Check for existing active session
        existing_session = await self._sessions.get_session_by_access_key(user.username)
        if existing_session:
            self._logger.info(f"Existing session found for user: {user.username}")
            return self._session_response_from_session(existing_session)

        # Else create a new session
        now = utc_now()
        new_session = Session(
            session_id=generate_session_id(),
            user_type=user.username,
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_duration),
        )

        self._logger.info(f"Creating new session for user: {user.username}")

        created_session = await self._sessions.create_session(new_session)
        return self._session_response_from_session(created_session)
