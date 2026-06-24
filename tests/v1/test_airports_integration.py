import pytest
from pymongo.errors import DuplicateKeyError

from app.repositories.airport import AirportRepository, ensure_airport_indexes
from app.schemas.v1.airport import AirportCreate, AirportSearchRequest
from app.services.airport import AirportService
from app.util.time import utc_now


async def _seed(service: AirportService, creates: list[AirportCreate]) -> None:
    for create in creates:
        await service.add_airport(create)


async def _search_icaos(service: AirportService, query: str) -> set[str]:
    response = await service.search_airports(AirportSearchRequest(query=query))
    return {a.icao for a in response.results}


class TestAirportSearch_Integration:
    @pytest.mark.asyncio
    async def test_search_by_each_field(
        self,
        airport_service_real: AirportService,
        sample_airport_creates: list[AirportCreate],
    ):
        await _seed(airport_service_real, sample_airport_creates)

        # by name
        assert await _search_icaos(airport_service_real, "Schiphol") == {"EHAM"}
        # by city
        assert await _search_icaos(airport_service_real, "new york") == {"KJFK"}
        # by country
        assert await _search_icaos(airport_service_real, "Kingdom") == {"EGLL"}
        # by iata (case-insensitive)
        assert await _search_icaos(airport_service_real, "ams") == {"EHAM"}
        # by icao
        assert await _search_icaos(airport_service_real, "kjfk") == {"KJFK"}

    @pytest.mark.asyncio
    async def test_search_no_match(
        self,
        airport_service_real: AirportService,
        sample_airport_creates: list[AirportCreate],
    ):
        await _seed(airport_service_real, sample_airport_creates)
        response = await airport_service_real.search_airports(
            AirportSearchRequest(query="nowhere-xyz")
        )
        assert response.results == []
        assert response.count == 0

    @pytest.mark.asyncio
    async def test_get_airport_by_code_icao_and_iata(
        self,
        airport_service_real: AirportService,
        sample_airport_creates: list[AirportCreate],
    ):
        await _seed(airport_service_real, sample_airport_creates)

        by_icao = await airport_service_real.get_airport_by_code("EHAM")
        by_iata = await airport_service_real.get_airport_by_code("AMS")
        assert by_icao is not None and by_iata is not None
        assert by_icao.id == by_iata.id
        # lowercase is normalised by the service
        by_lower = await airport_service_real.get_airport_by_code("eham")
        assert by_lower is not None and by_lower.icao == "EHAM"


class TestAirportSeed_Integration:
    @pytest.mark.asyncio
    async def test_unique_icao_index_blocks_duplicates(
        self,
        airport_repository_real: AirportRepository,
        airport_test_db,
        sample_airport_creates: list[AirportCreate],
    ):
        await ensure_airport_indexes(airport_test_db)
        collection = airport_test_db["airports"]

        doc = {
            **sample_airport_creates[0].model_dump(),
            "created_at": utc_now(),
            "updated_at": None,
        }
        await collection.insert_one(dict(doc))
        with pytest.raises(DuplicateKeyError):
            await collection.insert_one(dict(doc))

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent(
        self,
        airport_test_db,
        sample_airport_creates: list[AirportCreate],
    ):
        """The seed strategy (upsert by ICAO) must not create duplicates on re-run."""
        await ensure_airport_indexes(airport_test_db)
        collection = airport_test_db["airports"]

        async def run_seed() -> int:
            upserted = 0
            now = utc_now()
            for create in sample_airport_creates:
                seed_doc = {**create.model_dump(), "created_at": now, "updated_at": None}
                result = await collection.update_one(
                    {"icao": create.icao},
                    {"$setOnInsert": seed_doc},
                    upsert=True,
                )
                if result.upserted_id is not None:
                    upserted += 1
            return upserted

        first = await run_seed()
        second = await run_seed()

        assert first == len(sample_airport_creates)
        assert second == 0
        assert await collection.count_documents({}) == len(sample_airport_creates)
