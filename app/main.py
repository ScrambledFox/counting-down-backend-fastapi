from fastapi import FastAPI

from app.api.v1.routes import router as v1_api_router

app = FastAPI(title="CountingDown API", version="0.1.0")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


app.include_router(v1_api_router, prefix="/api/v1")
