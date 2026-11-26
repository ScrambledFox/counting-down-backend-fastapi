from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class S3ObjectInfo:
    size: int
    content_type: str | None


class S3Storage(Protocol):
    async def upload_object(
        self, *, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> None: ...

    async def get_object(self, *, bucket: str, key: str) -> bytes | None: ...

    async def get_object_exists(self, *, bucket: str, key: str) -> bool: ...

    async def get_object_info(self, *, bucket: str, key: str) -> S3ObjectInfo | None: ...

    async def generate_presigned_post(
        self, *, bucket: str, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> dict[str, Any]: ...

    async def delete_object(self, *, bucket: str, key: str) -> None: ...

    async def generate_presigned_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str: ...
