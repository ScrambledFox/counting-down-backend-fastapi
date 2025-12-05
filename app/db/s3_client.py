from contextlib import closing
from functools import lru_cache
from io import BytesIO

from boto3.s3.transfer import TransferConfig
from boto3.session import Session
from botocore.config import Config
from botocore.exceptions import ClientError
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
                ExtraArgs=extra_args if extra_args else None,  # type: ignore[arg-type]
                Config=self._transfer_cfg,
            )

        try:
            await run_in_threadpool(_upload)
        except ClientError:
            self._logger.exception("S3 upload failed", extra={"bucket": bucket, "key": key})
            raise

    async def get_object(self, *, bucket: str, key: str) -> bytes | None:
        self._logger.debug("Getting bytes from S3", extra={"bucket": bucket, "key": key})

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
                self._logger.info(
                    "S3 object not found",
                    extra={"bucket": bucket, "key": key},
                )
                return None
            self._logger.exception(
                "S3 get_object failed", extra={"bucket": bucket, "key": key}
            )
            raise

        self._logger.debug(
            "Got bytes from S3",
            extra={"bucket": bucket, "key": key, "length": len(data)},
        )
        return data

    async def delete_object(self, *, bucket: str, key: str) -> None:
        self._logger.debug("Deleting S3 object", extra={"bucket": bucket, "key": key})

        def _delete() -> None:
            self._client.delete_object(Bucket=bucket, Key=key)

        try:
            await run_in_threadpool(_delete)
        except ClientError:
            self._logger.exception("S3 delete_object failed", extra={"bucket": bucket, "key": key})
            raise

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

        try:
            url = await run_in_threadpool(_generate_url)
            self._logger.debug(
                "Generated presigned URL",
                extra={"bucket": bucket, "key": key, "url": url},
            )
            return url
        except ClientError:
            self._logger.exception("S3 presign failed", extra={"bucket": bucket, "key": key})
            raise


@lru_cache
def _get_s3_client() -> S3Client:
    session = Session(
        aws_access_key_id=settings.aws_access_key,
        aws_secret_access_key=settings.aws_secret_key,
        region_name=settings.aws_region,
    )
    cfg = Config(
        region_name=settings.aws_region,
        retries={"max_attempts": 5, "mode": "standard"},
        connect_timeout=5,
        read_timeout=60,
        signature_version="s3v4",
        max_pool_connections=20,
        s3={"addressing_style": "virtual"},
    )
    return session.client("s3", config=cfg)  # type: ignore


def get_s3_storage() -> S3Storage:
    client = _get_s3_client()
    return Boto3S3Storage(client=client)
