"""Unit tests for flight lookup service and route."""
from unittest.mock import AsyncMock, patch

import pytest

import app.services.flight_lookup as flight_lookup_module
from app.api.v1.flight_lookup import lookup_flight_route
from app.integrations.aerodatabox_client import AeroDataBoxError, RawFlightData
from app.schemas.v1.exceptions import BadRequestException, ServiceUnavailableException
from app.schemas.v1.flight_lookup import FlightLookupResponse
from app.services.flight_lookup import lookup_flight, normalize_flight_number

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_RAW_FLIGHT: dict = {
    "number": "KL123",
    "status": "Scheduled",
    "airline": {"name": "KLM Royal Dutch Airlines", "iata": "KL"},
    "departure": {
        "airport": {
            "iata": "AMS",
            "icao": "EHAM",
            "name": "Amsterdam Schiphol",
            "municipalityName": "Amsterdam",
            "countryCode": "NL",
        },
        "scheduledTime": {
            "local": "2026-06-25 12:30+02:00",
            "utc": "2026-06-25 10:30Z",
        },
    },
    "arrival": {
        "airport": {
            "iata": "LHR",
            "icao": "EGLL",
            "name": "London Heathrow",
            "municipalityName": "London",
            "countryCode": "GB",
        },
        "scheduledTime": {
            "local": "2026-06-25 12:50+01:00",
            "utc": "2026-06-25 11:50Z",
        },
    },
}


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory cache before each test."""
    flight_lookup_module._cache.clear()
    yield
    flight_lookup_module._cache.clear()


# ---------------------------------------------------------------------------
# normalize_flight_number
# ---------------------------------------------------------------------------


class TestNormalizeFlightNumber:
    def test_strips_whitespace(self):
        assert normalize_flight_number("  KL123  ") == "KL123"

    def test_removes_internal_spaces(self):
        assert normalize_flight_number("KL 123") == "KL123"

    def test_uppercases(self):
        assert normalize_flight_number("kl123") == "KL123"

    def test_removes_hyphens(self):
        assert normalize_flight_number("KL-123") == "KL123"

    def test_accepts_two_letter_prefix(self):
        assert normalize_flight_number("KL12") == "KL12"

    def test_accepts_three_letter_prefix(self):
        assert normalize_flight_number("BAW100") == "BAW100"

    def test_rejects_empty(self):
        with pytest.raises(BadRequestException):
            normalize_flight_number("")

    def test_rejects_too_short(self):
        with pytest.raises(BadRequestException):
            normalize_flight_number("A")

    def test_rejects_no_digit_suffix(self):
        with pytest.raises(BadRequestException):
            normalize_flight_number("ABCDE")

    def test_rejects_digits_only(self):
        with pytest.raises(BadRequestException):
            normalize_flight_number("1234")

    def test_rejects_special_characters(self):
        with pytest.raises(BadRequestException):
            normalize_flight_number("!!")


# ---------------------------------------------------------------------------
# lookup_flight service
# ---------------------------------------------------------------------------


class TestLookupFlightService:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_client(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ) as mock_client:
            result = await lookup_flight("KL123")

        mock_client.assert_called_once()
        assert result.cached is False
        assert len(result.candidates) == 1
        assert result.candidates[0].flight_number == "KL123"

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_call_client_twice(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ) as mock_client:
            first = await lookup_flight("KL123")
            second = await lookup_flight("KL123")

        assert mock_client.call_count == 1
        assert first.cached is False
        assert second.cached is True

    @pytest.mark.asyncio
    async def test_empty_results_no_exception(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await lookup_flight("KL123")

        assert result.candidates == []
        assert result.cached is False

    @pytest.mark.asyncio
    async def test_provider_error_raises_503(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            side_effect=AeroDataBoxError("auth failed", 401),
        ):
            with pytest.raises(ServiceUnavailableException) as exc_info:
                await lookup_flight("KL123")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_provider_timeout_raises_503(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            side_effect=AeroDataBoxError("timed out"),
        ):
            with pytest.raises(ServiceUnavailableException):
                await lookup_flight("KL123")

    @pytest.mark.asyncio
    async def test_provider_429_raises_503(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            side_effect=AeroDataBoxError("rate limit", 429),
        ):
            with pytest.raises(ServiceUnavailableException):
                await lookup_flight("KL123")

    @pytest.mark.asyncio
    async def test_response_does_not_contain_api_key(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ):
            result = await lookup_flight("KL123")

        dumped = result.model_dump_json()
        assert "api_key" not in dumped.lower()
        assert "rapidapi" not in dumped.lower()

    @pytest.mark.asyncio
    async def test_success_ttl_expiry_recalls_client(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ) as mock_client:
            await lookup_flight("KL123")
            # Manually expire the cache entry
            key = list(flight_lookup_module._cache.keys())[0]
            flight_lookup_module._cache[key] = (0.0, flight_lookup_module._cache[key][1])
            await lookup_flight("KL123")

        assert mock_client.call_count == 2

    @pytest.mark.asyncio
    async def test_no_results_ttl_expiry_recalls_client(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_client:
            await lookup_flight("KL999")
            key = list(flight_lookup_module._cache.keys())[0]
            flight_lookup_module._cache[key] = (0.0, flight_lookup_module._cache[key][1])
            await lookup_flight("KL999")

        assert mock_client.call_count == 2

    @pytest.mark.asyncio
    async def test_normalizes_query_before_caching(self):
        """Different casings/spacings of the same flight number hit the same cache entry."""
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ) as mock_client:
            await lookup_flight("kl 123")
            await lookup_flight("KL123")

        assert mock_client.call_count == 1

    @pytest.mark.asyncio
    async def test_candidate_fields_populated(self):
        with patch.object(
            flight_lookup_module.aerodatabox_client,
            "get_flights_by_number",
            new_callable=AsyncMock,
            return_value=[RawFlightData(data=SAMPLE_RAW_FLIGHT)],
        ):
            result = await lookup_flight("KL123")

        c = result.candidates[0]
        assert c.departure_airport.iata == "AMS"
        assert c.departure_airport.icao == "EHAM"
        assert c.arrival_airport.iata == "LHR"
        assert c.airline_name == "KLM Royal Dutch Airlines"
        assert c.scheduled_departure_time_local == "2026-06-25T12:30+02:00"
        assert c.scheduled_departure_time_utc == "2026-06-25T10:30Z"
        assert c.status == "Scheduled"
        assert c.source == "AeroDataBox"


# ---------------------------------------------------------------------------
# lookup_flight_route
# ---------------------------------------------------------------------------


class TestLookupFlightRoute:
    @pytest.mark.asyncio
    async def test_invalid_flight_number_returns_400(self):
        with patch("app.api.v1.flight_lookup.lookup_flight", new_callable=AsyncMock) as mock_svc:
            mock_svc.side_effect = BadRequestException("invalid")
            with pytest.raises(BadRequestException) as exc_info:
                await lookup_flight_route(flightNumber="!!", _session=None)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_lookup_returns_response(self):
        expected = FlightLookupResponse(
            query="KL123",
            normalized_flight_number="KL123",
            cached=False,
            candidates=[],
        )
        with patch("app.api.v1.flight_lookup.lookup_flight", new_callable=AsyncMock, return_value=expected):
            result = await lookup_flight_route(flightNumber="KL123", _session=None)
        assert result == expected
