import httpx
import pytest
from fastapi import status

from app.main import app


@pytest.mark.asyncio
async def test_health():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"status": "ok"}
