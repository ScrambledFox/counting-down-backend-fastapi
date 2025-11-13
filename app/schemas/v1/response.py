from pydantic import BaseModel, ConfigDict


class DeletedResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"detail": "Item has been deleted"})
