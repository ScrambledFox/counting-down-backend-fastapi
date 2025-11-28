from app.schemas.v1.user import User, UserType


class UserService:
    def __init__(self) -> None:
        pass

    def get_user_from_user_type(self, user_type: UserType) -> User:
        return User(username=user_type)
