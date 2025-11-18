from pydantic import BaseModel, ConfigDict


class DeletedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    deleted: bool = True