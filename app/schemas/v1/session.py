from datetime import datetime

from app.schemas.v1.base import CustomModel, DefaultMongoIdField
from app.schemas.v1.user import UserType
from app.util.user import get_other_user_type


class SessionBase(CustomModel):
    session_id: str
    user_type: UserType
    created_at: datetime
    expires_at: datetime

    def get_other_user(self) -> UserType:
        return get_other_user_type(self.user_type)


class Session(SessionBase):
    id: DefaultMongoIdField = None


class SessionResponse(SessionBase):
    pass
