import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_api_router
from app.api.v1.error_handlers import register_exception_handlers
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.indexes import ensure_all_indexes
from app.db.mongo_client import get_db
from app.schemas.v1.health import HealthResponse
from app.workers.job_handlers import build_job_handlers, in_process_job_kinds
from app.workers.job_runner import JobKind, run_jobs

settings = get_settings()


async def run_in_process_jobs(kinds: list[JobKind], stop_event: asyncio.Event) -> None:
    """Work on the enabled queues inside the web process until shutdown.

    Handlers are built inside the task so a misconfigured job dependency cannot stop the API
    from starting.
    """
    try:
        handlers = build_job_handlers(get_db(), kinds)
        await run_jobs(handlers, continuous=True, stop_event=stop_event)
    except Exception:
        get_logger(__name__).exception("In-process background jobs stopped")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = setup_logging()
    logger.info("Application startup")

    if settings.ensure_indexes_on_startup:
        await ensure_all_indexes(get_db())

    stop_event = asyncio.Event()
    kinds = in_process_job_kinds()
    jobs_task = asyncio.create_task(run_in_process_jobs(kinds, stop_event)) if kinds else None
    try:
        yield
    finally:
        stop_event.set()
        if jobs_task:
            # Cancelling mid-item is safe: the item's lease expires and it is retried.
            jobs_task.cancel()
            with suppress(asyncio.CancelledError):
                await jobs_task

        logger.info("Application shutdown")


app = FastAPI(title="CountingDown API", version="0.2.0", lifespan=lifespan)

if settings.frontend_urls and len(settings.frontend_urls) > 0:
    origins: list[str] = list(dict.fromkeys(settings.frontend_urls))
elif settings.frontend_url:
    origins = [settings.frontend_url]
else:
    origins = ["http://localhost:8080"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


app.include_router(v1_api_router)


@app.get("/health", tags=["meta"], response_model=HealthResponse)
def health() -> HealthResponse:
    logger = get_logger("health")
    logger.debug("Health check endpoint called")
    return HealthResponse(status="ok")
