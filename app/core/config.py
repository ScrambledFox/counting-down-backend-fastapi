from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    mongo_url: str
    mongo_db_name: str

    todos_collection_name: str

    model_config = SettingsConfigDict(
        env_file=".env",
        populate_by_name=True,
    )


settings = Settings()
