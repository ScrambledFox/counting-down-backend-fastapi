import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AeroDataBoxError(Exception):
    """Raised when the AeroDataBox API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RawFlightData:
    """Thin wrapper around a single parsed flight dict from the AeroDataBox response."""

    data: dict


class AeroDataBoxClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if not settings.aerodatabox_api_key:
            raise RuntimeError("AERODATABOX_API_KEY is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.aerodatabox_base_url,
                headers={
                    "X-RapidAPI-Key": settings.aerodatabox_api_key,
                    "X-RapidAPI-Host": settings.aerodatabox_api_host,
                },
                timeout=settings.aerodatabox_timeout_seconds,
            )
        return self._client

    async def get_flights_by_number(
        self,
        flight_number: str,
        date_from: str,
        date_to: str,
    ) -> list[RawFlightData]:
        """Call GET /flights/number/{flightNumber}/{dateFrom}/{dateTo}.

        Returns a list of raw flight dicts (may be empty).
        Raises AeroDataBoxError for any non-2xx response or network issue.
        """
        client = self._get_client()
        try:
            response = await client.get(f"/flights/number/{flight_number}/{date_from}/{date_to}")
        except httpx.TimeoutException as exc:
            logger.warning("AeroDataBox request timed out for flight %s", flight_number)
            raise AeroDataBoxError("Flight data service timed out") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "AeroDataBox request error for flight %s: %s", flight_number, type(exc).__name__
            )
            raise AeroDataBoxError("Flight data service is unavailable") from exc

        # 404 means no flights found for that number/range — treat as empty, not an error
        if response.status_code == 404:
            return []

        if response.status_code in (401, 403):
            logger.error("AeroDataBox authentication failed (status %d)", response.status_code)
            raise AeroDataBoxError(
                "Flight data service authentication failed", response.status_code
            )

        if response.status_code == 429:
            logger.warning("AeroDataBox rate limit exceeded")
            raise AeroDataBoxError("Flight data service rate limit exceeded", response.status_code)

        if not response.is_success:
            logger.error("AeroDataBox returned unexpected status %d", response.status_code)
            raise AeroDataBoxError(
                f"Flight data service returned an error ({response.status_code})",
                response.status_code,
            )

        payload = response.json()
        # AeroDataBox may return a bare array or {"flights": [...]}
        if isinstance(payload, list):
            return [RawFlightData(data=item) for item in payload]
        flights = payload.get("flights") or []
        return [RawFlightData(data=item) for item in flights]


aerodatabox_client = AeroDataBoxClient()
