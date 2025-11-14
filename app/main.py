from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.error_handlers import register_exception_handlers
from app.api.v1.routes import router as v1_api_router
from app.core.config import settings
from app.db.client import close_db_client, get_db_client
from app.schemas.v1.health import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # -- Startup code can go here
    await get_db_client()
    yield
    # -- Shutdown code can go here
    await close_db_client()


app = FastAPI(title="CountingDown API", version="0.1.0", lifespan=lifespan)

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


app.include_router(v1_api_router, prefix="/api/v1")


@app.get("/health", tags=["meta"], response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
