from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    frontend_url: str | None = None
    # Comma-separated list of frontend origins. If provided, this supersedes single frontend_url.
    frontend_urls: list[str] | None = None

    mongo_url: str = "mongodb://localhost:27017"
    mongo_app_name: str = "counting_down_app"

    todos_collection_name: str = "todos"
    messages_collection_name: str = "messages"
    flights_collection_name: str = "flights"
    airports_collection_name: str = "airports"

    model_config = SettingsConfigDict(env_file=".env", populate_by_name=True)

    @field_validator("frontend_urls", mode="before")
    @classmethod
    def split_frontend_urls(cls, v: str | list[str] | None):  # type: ignore[override]
        """Allow FRONTEND_URLS env var to be provided as a comma-separated string.

        Example:
            FRONTEND_URLS="https://a.example.com, https://b.example.com, http://localhost:3000"
        """
        if v is None:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            return parts or None
        return v


settings = Settings()
