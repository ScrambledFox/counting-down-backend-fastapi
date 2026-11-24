"""AWS sessions for the two integrations the backend uses.

Each integration has its own region and optional credentials, so the S3 bucket and the jobs
function may live in different regions and the wake-up can use an invoke-only identity:

* S3: ``AWS_S3_REGION`` (falls back to ``AWS_REGION``) and ``AWS_ACCESS_KEY``/``AWS_SECRET_KEY``.
* Job wake-up: ``JOB_WAKEUP_LAMBDA_REGION`` and ``JOB_WAKEUP_AWS_ACCESS_KEY``/``..._SECRET_KEY``.

When a key pair is not configured, boto3's default credential provider chain is used (the IAM
role on Lambda, ``AWS_PROFILE`` or SSO locally), so no long-lived keys are required there.
"""

from functools import lru_cache

from boto3.session import Session

from app.core.config import get_settings


@lru_cache
def _session(access_key: str | None, secret_key: str | None, region: str) -> Session:
    if access_key and secret_key:
        return Session(
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name=region
        )
    return Session(region_name=region)


def get_s3_session() -> Session:
    settings = get_settings()
    return _session(settings.aws_access_key, settings.aws_secret_key, settings.s3_region)


def get_job_wakeup_session() -> Session:
    settings = get_settings()
    return _session(
        settings.job_wakeup_aws_access_key,
        settings.job_wakeup_aws_secret_key,
        settings.job_wakeup_region,
    )
