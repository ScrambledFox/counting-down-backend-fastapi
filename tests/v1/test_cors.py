from starlette.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_first_configured_origin_allowed():
    """If multiple origins configured, the first should be allowed via CORS preflight."""
    if not settings.frontend_urls:
        # Not configured for multiple origins; skip so test suite passes in single-origin envs.
        return
    client = TestClient(app)
    origin = settings.frontend_urls[0]
    # Preflight OPTIONS request
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == origin
