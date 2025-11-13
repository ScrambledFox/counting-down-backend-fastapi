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

# Configure CORS middleware
origins: list[str] = []
if settings.frontend_url:
    origins.append(settings.frontend_url)
else:
    origins.append("http://localhost:3000")

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
