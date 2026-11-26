from __future__ import annotations

from contextlib import closing
from functools import lru_cache
from io import BytesIO
from typing import TYPE_CHECKING, Any

from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi.concurrency import run_in_threadpool

from app.core.aws import get_s3_session
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.s3 import S3ObjectInfo, S3Storage

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

settings = get_settings()


class Boto3S3Storage(S3Storage):
    _client: S3Client

    def __init__(self, client: S3Client) -> None:
        self._client = client
        self._logger = get_logger("s3")
        self._transfer_cfg = TransferConfig(
            multipart_threshold=16 * 1024 * 1024,
            multipart_chunksize=8 * 1024 * 1024,
            max_concurrency=4,
            use_threads=True,
        )

    async def upload_object(
        self,
        *,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> None:
        self._logger.debug(
            f"Uploading bytes to S3 with key: {key} and content_type: {content_type}",
            extra={"bucket": bucket, "key": key, "content_type": content_type},
        )

        def _upload() -> None:
            extra_args: dict[str, str] = {}
            if content_type:
                extra_args["ContentType"] = content_type

            buf = BytesIO(data)
            self._client.upload_fileobj(
                Fileobj=buf,
                Bucket=bucket,
                Key=key,
                ExtraArgs=extra_args if extra_args else None,
                Config=self._transfer_cfg,
            )

        try:
            await run_in_threadpool(_upload)
        except ClientError:
            self._logger.exception(
                f"S3 upload failed for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            raise

    async def get_object(self, *, bucket: str, key: str) -> bytes | None:
        self._logger.debug(
            f"Getting bytes from S3 for bucket: {bucket}, key: {key}",
            extra={"bucket": bucket, "key": key},
        )

        def _get() -> bytes:
            response = self._client.get_object(Bucket=bucket, Key=key)
            body = response["Body"]
            with closing(body):
                return body.read()

        try:
            data = await run_in_threadpool(_get)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code == "NoSuchKey":
                self._logger.warning(
                    "S3 object not found",
                    extra={"bucket": bucket, "key": key},
                )
                return None
            self._logger.exception(
                f"S3 get_object failed for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            raise

        self._logger.debug(
            f"Got bytes from S3 for bucket: {bucket}, key: {key}, length: {len(data)}",
            extra={"bucket": bucket, "key": key, "length": len(data)},
        )
        return data

    async def get_object_exists(self, *, bucket: str, key: str) -> bool:
        self._logger.debug(
            f"Checking if S3 object exists for bucket: {bucket}, key: {key}",
            extra={"bucket": bucket, "key": key},
        )

        def _head() -> bool:
            self._client.head_object(Bucket=bucket, Key=key)
            return True

        try:
            return await run_in_threadpool(_head)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code == "404" or error_code == "NoSuchKey":
                self._logger.debug(
                    f"S3 object does not exist for bucket: {bucket}, key: {key}",
                    extra={"bucket": bucket, "key": key},
                )
                return False
            self._logger.exception(
                f"S3 head_object failed for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            raise

    async def get_object_info(self, *, bucket: str, key: str) -> S3ObjectInfo | None:
        def _head() -> S3ObjectInfo:
            response = self._client.head_object(Bucket=bucket, Key=key)
            return S3ObjectInfo(
                size=int(response["ContentLength"]), content_type=response.get("ContentType")
            )

        try:
            return await run_in_threadpool(_head)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            self._logger.error(
                "S3 head_object failed",
                extra={"bucket": bucket, "error_type": type(exc).__name__},
            )
            raise

    async def generate_presigned_post(
        self, *, bucket: str, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> dict[str, Any]:
        """A browser form upload for exactly this key, content type and size range.

        S3 enforces the conditions, so the browser cannot choose another key, store a different
        content type or exceed the size limit. The URL and fields are credentials for one upload
        and are never logged.
        """

        def _post() -> dict[str, Any]:
            return self._client.generate_presigned_post(
                Bucket=bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, max_bytes],
                ],
                ExpiresIn=expires_in,
            )

        return await run_in_threadpool(_post)

    async def delete_object(self, *, bucket: str, key: str) -> None:
        self._logger.debug(
            f"Deleting S3 object for bucket: {bucket}, key: {key}",
            extra={"bucket": bucket, "key": key},
        )

        def _delete() -> None:
            self._client.delete_object(Bucket=bucket, Key=key)

        try:
            await run_in_threadpool(_delete)
        except ClientError:
            self._logger.exception(
                f"S3 delete_object failed for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            raise

    async def generate_presigned_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in: int = 3600,
    ) -> str:
        self._logger.debug(
            f"Generating presigned URL for bucket: {bucket}, key: {key}, expires_in: {expires_in}"
        )

        def _generate_url() -> str:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )

        try:
            url = await run_in_threadpool(_generate_url)
            self._logger.debug(
                f"Generated presigned URL for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            return url
        except ClientError:
            self._logger.exception(
                f"S3 presign failed for bucket: {bucket}, key: {key}",
                extra={"bucket": bucket, "key": key},
            )
            raise


@lru_cache
def _get_s3_client() -> S3Client:
    session = get_s3_session()
    cfg = Config(
        region_name=settings.s3_region,
        retries={"max_attempts": 5, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
        signature_version="s3v4",
        max_pool_connections=20,
        s3={"addressing_style": "virtual"},
    )
    return session.client("s3", config=cfg)


def get_s3_storage() -> S3Storage:
    client = _get_s3_client()
    return Boto3S3Storage(client=client)
