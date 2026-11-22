from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.repositories.advent import AdventRepository
from app.schemas.v1.user import UserType


@pytest.mark.asyncio
@pytest.mark.parametrize("year", [2026, 2027])
async def test_advent_lists_and_count_only_include_current_year(year):
    """Old gifts stay stored, but lists, day lookups and counts exclude them."""
    documents = [
        {
            "day": day,
            "uploaded_by": user,
            "uploaded_at": uploaded_at,
            "title": "Gift",
            "description": "",
            "type": "cute",
            "image_key": f"gift-{index}",
            "content_type": "image/png",
        }
        for index, (day, user, uploaded_at) in enumerate(
            [
                (1, UserType.JORIS, datetime(year - 1, 12, 31, 23, 59, 59, tzinfo=UTC)),
                (1, UserType.JORIS, datetime(year, 1, 1, tzinfo=UTC)),
                (2, UserType.JORIS, datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC)),
                (1, UserType.JORIS, datetime(year + 1, 1, 1, tzinfo=UTC)),
                (1, UserType.DANFENG, datetime(year, 11, 21, tzinfo=UTC)),
            ]
        )
    ]

    def matching(query):
        bounds = query["uploaded_at"]
        return [
            doc
            for doc in documents
            if doc["uploaded_by"] == query["uploaded_by"]
            and bounds["$gte"] <= doc["uploaded_at"] < bounds["$lt"]
            and ("day" not in query or doc["day"] == query["day"])
        ]

    def find(query):
        cursor = Mock()
        cursor.sort.return_value = cursor
        cursor.to_list = AsyncMock(return_value=matching(query))
        return cursor

    collection = Mock()
    collection.find.side_effect = find
    collection.count_documents = AsyncMock(side_effect=lambda query: len(matching(query)))
    db = Mock()
    db.__getitem__ = Mock(return_value=collection)
    repo = AdventRepository(db)

    with patch("app.repositories.advent.utc_now", return_value=datetime(year, 11, 21, tzinfo=UTC)):
        gifts = await repo.get_advents_uploaded_by(UserType.JORIS)
        assert [gift.image_key for gift in gifts] == ["gift-1", "gift-2"]
        day_gifts = await repo.get_advents_day_uploaded_by(1, UserType.JORIS)
        assert [gift.image_key for gift in day_gifts] == ["gift-1"]
        assert await repo.count_advents_uploaded_by(UserType.JORIS) == 2
        partner_gifts = await repo.get_advents_uploaded_by(UserType.DANFENG)
        assert [gift.image_key for gift in partner_gifts] == ["gift-4"]

    assert len(documents) == 5
