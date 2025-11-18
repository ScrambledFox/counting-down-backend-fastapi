from pydantic import ConfigDict

from app.schemas.v1.base import CustomModel


class DeletedResponse(CustomModel):
    model_config = ConfigDict(from_attributes=True)
    deleted: bool = True
