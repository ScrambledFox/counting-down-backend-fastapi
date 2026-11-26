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


@pytest.mark.asyncio
async def test_readiness_reports_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    class Database:
        def __init__(self, fail: bool) -> None:
            self.fail = fail

        async def command(self, _name: str) -> dict:
            if self.fail:
                raise ConnectionError("synthetic outage")
            return {"ok": 1}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        monkeypatch.setattr(main_module, "get_db", lambda: Database(fail=False))
        ok = await ac.get("/health/ready")
        monkeypatch.setattr(main_module, "get_db", lambda: Database(fail=True))
        down = await ac.get("/health/ready")

    assert (ok.status_code, ok.json()) == (200, {"status": "ok"})
    assert (down.status_code, down.json()) == (503, {"status": "unavailable"})
