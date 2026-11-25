"""Load secrets from SSM Parameter Store into the environment at Lambda cold start.

Parameters under ``SSM_PARAMETER_PATH`` (for example ``/bibi/prod/jobs``) become environment
variables named after their last path segment (``/bibi/prod/jobs/MONGO_URL`` -> ``MONGO_URL``).
This must run before any application module reads settings, so it depends only on boto3.
Values are never logged.
"""

import os
from typing import Any

import boto3

SSM_PATH_ENV = "SSM_PARAMETER_PATH"


def load_parameters_into_environ(client: Any | None = None) -> list[str]:
    """Copy decrypted parameters into ``os.environ``; return the variable names loaded."""
    path = os.environ.get(SSM_PATH_ENV)
    if not path:
        return []
    ssm = client or boto3.client("ssm")
    paginator = ssm.get_paginator("get_parameters_by_path")
    loaded: list[str] = []
    for page in paginator.paginate(Path=path, WithDecryption=True, Recursive=False):
        for parameter in page["Parameters"]:
            name = parameter["Name"].rsplit("/", 1)[-1]
            os.environ[name] = parameter["Value"]
            loaded.append(name)
    return sorted(loaded)
