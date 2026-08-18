from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.schemas.v1.relationship_profile import (
    RelationshipPersonProfile,
    RelationshipProfile,
    RelationshipProfileUpdate,
    default_relationship_profile,
)
from app.schemas.v1.user import UserType
from app.services.relationship_profile import RelationshipProfileService


@pytest.mark.asyncio
async def test_relationship_profile_defaults_describe_the_long_distance_setup() -> None:
    service = RelationshipProfileService(SimpleNamespace(get=AsyncMock(return_value=None)))

    profile = await service.get()
    ai_context = await service.get_ai_context()

    assert profile.relationship_mode == "LONG_DISTANCE"
    assert {person.user_type: person.location for person in profile.people} == {
        UserType.JORIS: "Netherlands",
        UserType.DANFENG: "Stockholm",
    }
    assert ai_context.currently_together is False
    assert "work remotely" in ai_context.practical_notes


@pytest.mark.asyncio
async def test_expired_visit_is_not_presented_to_xiaobao_as_current() -> None:
    stored = default_relationship_profile().model_copy(
        update={
            "currently_together": True,
            "together_through": date.today() - timedelta(days=1),
        }
    )
    service = RelationshipProfileService(SimpleNamespace(get=AsyncMock(return_value=stored)))

    context = await service.get_ai_context()

    assert context.currently_together is False
    assert context.together_through is None


@pytest.mark.asyncio
async def test_profile_update_records_the_authenticated_editor() -> None:
    profile = default_relationship_profile()
    payload = RelationshipProfileUpdate.model_validate(
        profile.model_dump(exclude={"id", "created_at", "updated_at", "updated_by_user_type"})
    )
    saved = RelationshipProfile.model_validate(payload.model_dump())
    repository = SimpleNamespace(save=AsyncMock(return_value=saved))
    service = RelationshipProfileService(repository)

    result = await service.update(payload, UserType.DANFENG)

    assert result == saved
    repository.save.assert_awaited_once_with(payload, UserType.DANFENG)


def test_profile_requires_both_fixed_users_and_valid_timezones() -> None:
    profile = default_relationship_profile()
    duplicate_people = [profile.people[0], profile.people[0]]

    with pytest.raises(ValidationError, match="Joris and Danfeng exactly once"):
        RelationshipProfileUpdate(
            relationship_mode="LONG_DISTANCE",
            people=duplicate_people,
        )

    with pytest.raises(ValidationError, match="valid IANA timezone"):
        RelationshipPersonProfile(
            user_type=UserType.JORIS,
            preferred_name="Joris",
            timezone="Amsterdam-ish",
        )
