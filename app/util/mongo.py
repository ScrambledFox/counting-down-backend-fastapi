from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.models.mongo import Document
from app.schemas.v1.base import to_mongo_object_id


def from_mongo(doc: Document) -> Document:
    """
    Return a shallow copy of `doc` where a MongoDB '_id' field is replaced
    by an 'id' field containing the string representation of the original value.

    Example:
        {"_id": ObjectId("..."), "name": "x"} -> {"id": "507f1f77bcf86cd799439011", "name": "x"}
    """
    out: Document = doc.copy()
    if "_id" in out:
        raw = out.pop("_id")
        # Convert ObjectId (or any other value) to its string form
        out["id"] = str(raw) if raw is not None else None
    return out


def _normalize_filter_rec(filter_obj: Any) -> Any:
    """Recursively normalize a Mongo filter, converting any string `_id` occurrences
    (including in `$in`/`$nin`) to ObjectId and raising on invalid strings.
    """
    if not isinstance(filter_obj, Mapping):
        return filter_obj

    # Cast to a properly parameterized Mapping so the type checker knows key is str
    mapping = cast(Mapping[str, Any], filter_obj)

    normalized: dict[str, Any] = {}
    for key, value in mapping.items():
        if key == "_id":
            # Direct match on _id
            if isinstance(value, list):
                # Value may be an untyped list; cast to list[Any] so the element type is known
                normalized[key] = [to_mongo_object_id(v) for v in cast(list[Any], value)]
            elif isinstance(value, Mapping):
                # Operators on _id
                sub: dict[str, Any] = {}
                sub_mapping = cast(Mapping[str, Any], value)
                for op, op_val in sub_mapping.items():
                    if op in ("$in", "$nin") and isinstance(op_val, list):
                        sub[op] = [to_mongo_object_id(v) for v in cast(list[Any], op_val)]
                    else:
                        sub[op] = _normalize_filter_rec(op_val)
                normalized[key] = sub
            else:
                normalized[key] = to_mongo_object_id(value)
        elif key in ("$and", "$or", "$nor") and isinstance(value, list):
            normalized[key] = [_normalize_filter_rec(v) for v in cast(list[Any], value)]
        else:
            normalized[key] = _normalize_filter_rec(value) if isinstance(value, Mapping) else value
    return normalized


def normalize_mongo_filter(filter_obj: Any | None) -> Any | None:
    """Public helper to normalize/enforce id types in Mongo filters.

    - Converts string `_id` values (including `$in`/`$nin`) to ObjectId
    - Recurses through `$and`/`$or`/`$nor`.
    - Raises on invalid 24-hex strings for `_id` via `to_mongo_object_id`.
    """
    if filter_obj is None:
        return None
    return _normalize_filter_rec(filter_obj)


class StrictCollection:
    """Wrap an AsyncIOMotorCollection to enforce/convert `_id` in filters.

    Only a subset of commonly used methods are wrapped; others are forwarded.
    """

    def __init__(self, collection: Any) -> None:
        self._col = collection

    # Reads
    def find(self, filter: Any | None = None, *args: Any, **kwargs: Any):  # noqa: A003
        return self._col.find(normalize_mongo_filter(filter), *args, **kwargs)

    async def find_one(self, filter: Any | None = None, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.find_one(normalize_mongo_filter(filter), *args, **kwargs)

    # Writes
    async def update_one(self, filter: Any, update: Any, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.update_one(normalize_mongo_filter(filter), update, *args, **kwargs)

    async def update_many(self, filter: Any, update: Any, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.update_many(normalize_mongo_filter(filter), update, *args, **kwargs)

    async def delete_one(self, filter: Any, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.delete_one(normalize_mongo_filter(filter), *args, **kwargs)

    async def delete_many(self, filter: Any, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.delete_many(normalize_mongo_filter(filter), *args, **kwargs)

    async def replace_one(self, filter: Any, replacement: Any, *args: Any, **kwargs: Any):  # noqa: A003
        return await self._col.replace_one(
            normalize_mongo_filter(filter), replacement, *args, **kwargs
        )

    async def insert_one(self, document: Any, *args: Any, **kwargs: Any):
        return await self._col.insert_one(document, *args, **kwargs)

    async def insert_many(self, documents: list[Any], *args: Any, **kwargs: Any):
        return await self._col.insert_many(documents, *args, **kwargs)

    # Misc passthroughs
    def __getattr__(self, item: str) -> Any:  # Fallback for other methods
        return getattr(self._col, item)


class StrictDatabase:
    """Wrap an AsyncIOMotorDatabase to auto-wrap collections as StrictCollection."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def __getitem__(self, name: str) -> StrictCollection:
        return StrictCollection(self._db[name])

    def __getattr__(self, item: str) -> Any:
        return getattr(self._db, item)
