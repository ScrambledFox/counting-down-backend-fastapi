from datetime import datetime

from app.schemas.v1.base import CustomModel, DefaultMongoIdField
from app.schemas.v1.user import UserType


class SessionBase(CustomModel):
    session_id: str
    user_type: UserType
    created_at: datetime
    expires_at: datetime


class Session(SessionBase):
    id: DefaultMongoIdField = None


class SessionResponse(SessionBase):
    pass
