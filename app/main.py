from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.routes import router as v1_api_router
from app.db.client import close_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code can go here
    yield
    # Shutdown code can go here
    close_client()


app = FastAPI(title="CountingDown API", version="0.1.0", lifespan=lifespan)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


app.include_router(v1_api_router, prefix="/api/v1")
