from typing import Protocol

from app.models.mongo import AsyncClient, AsyncDB


class MongoDBClient(Protocol):
    @property
    def client(self) -> AsyncClient: ...

    def get_db(self, db_name: str) -> AsyncDB: ...
