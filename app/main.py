from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.v1 import router as v1_api_router
from app.api.v1.error_handlers import register_exception_handlers
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.schemas.v1.health import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = setup_logging()
    logger.info("Application startup")
    # -- Startup code can go here
    try:
        yield
    finally:
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
