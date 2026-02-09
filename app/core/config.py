from functools import lru_cache

from pydantic import field_validator, model_validator
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
    advent_collection_name: str = "advents"
    sessions_collection_name: str = "sessions"
    image_metadata_collection_name: str = "images"

    aws_s3_image_folder: str = "images/"
    aws_s3_thumbnail_folder: str = "thumbnails/"
    thumbnail_size: int = 128
    thumbnail_xl_size: int = 1200
    # Optional explicit list of thumbnail sizes (comma-separated). If provided, supersedes
    # thumbnail_size/thumbnail_xl_size.
    thumbnail_sizes: list[int] | None = None
    # Allow custom thumbnail sizes outside the configured list, within min/max bounds.
    thumbnail_allow_custom_sizes: bool = True
    thumbnail_min_size: int = 32
    thumbnail_max_size: int = 2000
    aws_s3_presign_expires: int = 3600
    aws_s3_max_presign_expires: int = 1 * 24 * 3600  # 1 days in seconds

    access_key_danfeng: str | None = None
    access_key_joris: str | None = None
    session_duration: int = 7 * 24 * 60 * 60  # 7 days in seconds

    aws_region: str = "eu-west-1"
    aws_s3_bucket: str = "my-app-bucket"

    aws_access_key: str | None = None
    aws_secret_key: str | None = None

    default_page_size: int = 20
    max_page_size: int = 100

    model_config = SettingsConfigDict(env_file=".env", populate_by_name=True, case_sensitive=False)

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

    @field_validator("thumbnail_sizes", mode="before")
    @classmethod
    def split_thumbnail_sizes(cls, v: str | list[int] | None):  # type: ignore[override]
        """Allow THUMBNAIL_SIZES env var to be provided as a comma-separated string.

        Example:
            THUMBNAIL_SIZES="128, 512, 1200"
        """
        if v is None:
            return None
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            sizes: list[int] = []
            for part in parts:
                try:
                    sizes.append(int(part))
                except ValueError as exc:
                    raise ValueError(f"Invalid thumbnail size: {part}") from exc
            return sizes or None
        return v

    @model_validator(mode="after")
    def require_access_keys_in_production(self) -> "Settings":
        if self.app_env.lower() == "prod":
            missing: list[str] = []
            if not self.access_key_danfeng:
                missing.append("ACCESS_KEY_DANFENG")
            if not self.access_key_joris:
                missing.append("ACCESS_KEY_JORIS")
            if missing:
                raise ValueError(
                    "Missing required access key env vars in production: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
