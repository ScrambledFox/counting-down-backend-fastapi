import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.v1.airport import (
    add_airport,
    get_airport_info,
    list_airports,
    search_airports,
)
from app.schemas.v1.airport import Airport, AirportCreate
from app.schemas.v1.exceptions import NotFoundException
from app.services.airport import AirportService


class TestAirportRoutes:
    """Unit tests for airport API routes."""

    @pytest.mark.asyncio
    async def test_list_airports(self, sample_airports: list[Airport]):
        mock_service = Mock(spec=AirportService)
        mock_service.list_airports = AsyncMock(return_value=sample_airports)

        result = await list_airports(airport_service=mock_service)

        assert result == sample_airports
        mock_service.list_airports.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_search_airports(self, sample_airports: list[Airport]):
        mock_service = Mock(spec=AirportService)
        mock_service.search_airports = AsyncMock(return_value=sample_airports[:1])

        result = await search_airports(query="amsterdam", airport_service=mock_service)

        assert result == sample_airports[:1]
        mock_service.search_airports.assert_called_once_with("amsterdam")

    @pytest.mark.asyncio
    async def test_get_airport_by_code_success(self, sample_airports: list[Airport]):
        mock_service = Mock(spec=AirportService)
        mock_service.get_airport_by_code = AsyncMock(return_value=sample_airports[0])

        result = await get_airport_info(airport_code="EHAM", airport_service=mock_service)

        assert result == sample_airports[0]
        mock_service.get_airport_by_code.assert_called_once_with("EHAM")

    @pytest.mark.asyncio
    async def test_get_airport_by_code_not_found(self):
        mock_service = Mock(spec=AirportService)
        mock_service.get_airport_by_code = AsyncMock(return_value=None)

        with pytest.raises(NotFoundException) as exc_info:
            await get_airport_info(airport_code="ZZZZ", airport_service=mock_service)

        assert "ZZZZ" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_add_airport(self, sample_airports: list[Airport]):
        airport_create = AirportCreate(
            icao="EGLL",
            iata="LHR",
            name="London Heathrow Airport",
            city="London",
            country="United Kingdom",
            longitude=-0.461941,
            latitude=51.4706,
        )
        mock_service = Mock(spec=AirportService)
        mock_service.add_airport = AsyncMock(return_value=sample_airports[0])

        result = await add_airport(airport_data=airport_create, airport_service=mock_service)

        assert result == sample_airports[0]
        mock_service.add_airport.assert_called_once_with(airport_create)


class TestAirportService:
    """Unit tests for AirportService."""

    @pytest.mark.asyncio
    async def test_search_passthrough(
        self, airport_service_mock: AirportService, airport_repository_mock: Mock
    ):
        airport_repository_mock.search_airports.return_value = []
        result = await airport_service_mock.search_airports("ams")
        assert result == []
        airport_repository_mock.search_airports.assert_called_once_with("ams")

    @pytest.mark.asyncio
    async def test_get_by_code_uppercases(
        self, airport_service_mock: AirportService, airport_repository_mock: Mock
    ):
        airport_repository_mock.get_airport_by_code.return_value = None
        await airport_service_mock.get_airport_by_code("eham")
        airport_repository_mock.get_airport_by_code.assert_called_once_with("EHAM")

    @pytest.mark.asyncio
    async def test_add_airport_sets_created_at(
        self,
        airport_service_mock: AirportService,
        airport_repository_mock: Mock,
        sample_airport_creates: list[AirportCreate],
    ):
        fixed_now = datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
        airport_create = sample_airport_creates[0]

        with patch("app.services.airport.utc_now", return_value=fixed_now):
            airport_repository_mock.create_airport.side_effect = lambda airport: airport
            created = await airport_service_mock.add_airport(airport_create)

        assert created.created_at == fixed_now
        assert created.icao == airport_create.icao
        airport_repository_mock.create_airport.assert_called_once()
