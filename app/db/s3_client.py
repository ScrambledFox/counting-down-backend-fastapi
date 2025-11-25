from functools import lru_cache

from boto3.session import Session
from fastapi.concurrency import run_in_threadpool
from types_boto3_s3 import S3Client

from app.core.config import settings
from app.core.logging import get_logger
from app.models.s3 import S3Storage


class Boto3S3Storage(S3Storage):
    _client: S3Client

    def __init__(self, client: S3Client) -> None:
        self._client = client
        self._logger = get_logger("s3")

    async def upload_bytes(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        self._logger.debug(
            "Uploading bytes to S3",
            extra={"bucket": bucket, "key": key, "content_type": content_type},
        )

        def _upload() -> None:
            if content_type:
                self._client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
            else:
                self._client.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=data,
                )

        await run_in_threadpool(_upload)

    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        self._logger.debug("Getting bytes from S3", extra={"bucket": bucket, "key": key})

        def _get() -> bytes:
            response = self._client.get_object(Bucket=bucket, Key=key)
            body = response["Body"].read()
            return body

        data = await run_in_threadpool(_get)
        self._logger.debug(
            "Got bytes from S3",
            extra={"bucket": bucket, "key": key, "length": len(data)},
        )
        return data

    async def delete_object(self, *, bucket: str, key: str) -> None:
        self._logger.debug("Deleting S3 object", extra={"bucket": bucket, "key": key})

        def _delete() -> None:
            self._client.delete_object(Bucket=bucket, Key=key)

        await run_in_threadpool(_delete)

    async def generate_presigned_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        self._logger.debug(
            "Generating presigned URL",
            extra={"bucket": bucket, "key": key, "expires_in": expires_in},
        )

        def _generate_url() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        url = await run_in_threadpool(_generate_url)
        self._logger.debug(
            "Generated presigned URL",
            extra={"bucket": bucket, "key": key, "url": url},
        )
        return url


@lru_cache
def _get_s3_client() -> S3Client:
    return Session(
        aws_access_key_id=settings.aws_access_key,
        aws_secret_access_key=settings.aws_secret_key,
        region_name=settings.aws_region,
    ).client("s3")  # type: ignore


def get_s3_storage() -> S3Storage:
    client = _get_s3_client()
    return Boto3S3Storage(client=client)
