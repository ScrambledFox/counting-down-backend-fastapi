from enum import Enum

from app.schemas.v1.base import CustomModel


class UserEnum(str, Enum):
    JORIS = "Joris"
    DANFENG = "Danfeng"


class User(CustomModel):
    username: UserEnum
