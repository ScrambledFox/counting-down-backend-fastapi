from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"

    frontend_url: str | None = None

    mongo_url: str = "mongodb://localhost:27017"
    mongo_app_name: str = "counting_down_app"

    todos_collection_name: str = "todos"
    messages_collection_name: str = "messages"
    flights_collection_name: str = "flights"
    airports_collection_name: str = "airports"

    model_config = SettingsConfigDict(env_file=".env", populate_by_name=True)


settings = Settings()
