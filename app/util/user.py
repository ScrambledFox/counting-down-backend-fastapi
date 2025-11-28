from app.schemas.v1.user import UserType


def get_other_user_type(user_type: UserType) -> UserType:
    if user_type == UserType.DANFENG:
        return UserType.JORIS
    else:
        return UserType.DANFENG
