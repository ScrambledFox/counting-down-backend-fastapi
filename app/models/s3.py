from typing import Protocol


class S3Storage(Protocol):
    async def upload_object(
        self, *, bucket: str, key: str, data: bytes, content_type: str | None = None
    ) -> None: ...

    async def get_object(self, *, bucket: str, key: str) -> bytes | None: ...

    async def delete_object(self, *, bucket: str, key: str) -> None: ...

    async def generate_presigned_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str: ...
