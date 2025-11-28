from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

# Document type alias for MongoDB documents
type Document = dict[str, Any]

type Query = dict[str, str | int | float | bool]

type AsyncDB = AsyncIOMotorDatabase[Document]
type AsyncClient = AsyncIOMotorClient[Document]
