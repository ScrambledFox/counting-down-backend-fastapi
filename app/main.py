import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_api_router
from app.api.v1.error_handlers import register_exception_handlers
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.mongo_client import get_db
from app.repositories.mediation import ensure_mediation_indexes
from app.schemas.v1.health import HealthResponse
from app.workers.mediation_worker import run_mediation_worker

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = setup_logging()
    logger.info("Application startup")

    await ensure_mediation_indexes(get_db())
    worker_stop_event: asyncio.Event | None = None
    worker_task: asyncio.Task[None] | None = None

    if settings.mediation_worker_enabled:
        worker_stop_event = asyncio.Event()
        worker_task = asyncio.create_task(run_mediation_worker(worker_stop_event))
    try:
        yield
    finally:
        if worker_stop_event:
            worker_stop_event.set()
        if worker_task:
            worker_task.cancel()

        logger.info("Application shutdown")


app = FastAPI(title="CountingDown API", version="0.2.0", lifespan=lifespan, prefix="/api")

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
