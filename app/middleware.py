from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.main import app

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
