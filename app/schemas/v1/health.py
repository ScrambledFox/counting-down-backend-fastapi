from app.schemas.v1.base import CustomModel


class HealthResponse(CustomModel):
    status: str
