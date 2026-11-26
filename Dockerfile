# syntax=docker/dockerfile:1.7
#
# One source tree and dependency set, two thin Lambda targets:
#   docker buildx build --platform linux/arm64 --target api  -t bibi-api  .
#   docker buildx build --platform linux/arm64 --target jobs -t bibi-jobs .
# Both targets share every layer up to and including the application code, so the registry
# stores the dependencies once. Only the entry point differs: the API runs uvicorn behind the
# Lambda Web Adapter (response streaming), the jobs function runs a plain Python handler.

ARG PYTHON_IMAGE=python:3.14-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.11
ARG LAMBDA_ADAPTER_IMAGE=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1

FROM ${UV_IMAGE} AS uv
FROM ${LAMBDA_ADAPTER_IMAGE} AS lambda-adapter

FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group lambda --no-install-project \
    && rm /usr/local/bin/uv
COPY app ./app
COPY scripts ./scripts
# Indexes are created by scripts/ensure_indexes.py at deploy time, and background queues are
# served by the jobs function, not by API instances.
ENV ENSURE_INDEXES_ON_STARTUP=false \
    LOG_FORMAT=json \
    IMAGE_WORKER_ENABLED=false \
    MEDIATION_WORKER_ENABLED=false \
    XIAOBAO_IN_PROCESS_JOBS_ENABLED=false
RUN useradd --system --uid 10001 app
USER app

FROM base AS api
COPY --from=lambda-adapter /lambda-adapter /opt/extensions/lambda-adapter
ENV PORT=8080 \
    AWS_LWA_INVOKE_MODE=response_stream \
    AWS_LWA_READINESS_CHECK_PATH=/health
EXPOSE 8080
CMD ["uvicorn", "app.lambda_api:app", "--host", "0.0.0.0", "--port", "8080"]

FROM base AS jobs
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["app.lambda_jobs.handler"]
