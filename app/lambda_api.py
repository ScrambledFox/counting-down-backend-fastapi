"""AWS Lambda entry point for the HTTP API.

The container runs ``uvicorn app.lambda_api:app`` behind the Lambda Web Adapter, which turns
Function URL requests into HTTP requests and streams responses back (Server-Sent Events for
Xiao Bao). Secrets live in SSM Parameter Store and must be in the environment before any
application module reads settings, so they are loaded here, before ``app.main`` is imported.
"""

from app.core.ssm import load_parameters_into_environ

load_parameters_into_environ()

from app.main import app  # noqa: E402

__all__ = ["app"]
