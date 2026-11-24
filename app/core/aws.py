"""Shared AWS session.

Heroku provides credentials through the app-specific ``AWS_ACCESS_KEY`` / ``AWS_SECRET_KEY``
settings. Everywhere else (an IAM role on Lambda, ``AWS_PROFILE`` or SSO locally) boto3's default
credential provider chain is used, so no long-lived keys are needed.
"""

from functools import lru_cache

from boto3.session import Session

from app.core.config import get_settings


@lru_cache
def get_aws_session() -> Session:
    settings = get_settings()
    if settings.aws_access_key and settings.aws_secret_key:
        return Session(
            aws_access_key_id=settings.aws_access_key,
            aws_secret_access_key=settings.aws_secret_key,
            region_name=settings.aws_region,
        )
    return Session(region_name=settings.aws_region)
