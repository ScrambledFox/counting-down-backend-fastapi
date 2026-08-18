from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from app.schemas.v1.base import CustomModel, DefaultMongoIdField
from app.schemas.v1.user import UserType


class RelationshipMode(str, Enum):
    LONG_DISTANCE = "LONG_DISTANCE"
    SAME_LOCATION = "SAME_LOCATION"
    HYBRID = "HYBRID"


class RelationshipPersonProfile(CustomModel):
    user_type: UserType
    preferred_name: str = Field(min_length=1, max_length=80)
    location: str = Field(default="", max_length=160)
    timezone: str = Field(default="", max_length=80)
    personality_notes: str = Field(default="", max_length=3000)
    preferences_notes: str = Field(default="", max_length=3000)

    @field_validator("preferred_name", "location", "timezone", mode="before")
    @classmethod
    def strip_short_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if not value:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "Timezone must be a valid IANA timezone, such as Europe/Amsterdam"
            ) from exc
        return value


class RelationshipProfileContent(CustomModel):
    relationship_mode: RelationshipMode = RelationshipMode.LONG_DISTANCE
    currently_together: bool = False
    together_through: date | None = None
    relationship_notes: str = Field(default="", max_length=4000)
    practical_notes: str = Field(default="", max_length=4000)
    people: list[RelationshipPersonProfile] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def require_both_people_once(self) -> RelationshipProfileContent:
        people = [person.user_type for person in self.people]
        if set(people) != {UserType.JORIS, UserType.DANFENG} or len(set(people)) != 2:
            raise ValueError("Relationship context must contain Joris and Danfeng exactly once")
        return self


class RelationshipProfileUpdate(RelationshipProfileContent):
    pass


class RelationshipProfile(RelationshipProfileContent):
    id: DefaultMongoIdField = None
    updated_by_user_type: UserType | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RelationshipProfileAIContext(CustomModel):
    relationship_mode: RelationshipMode
    currently_together: bool
    together_through: date | None = None
    relationship_notes: str = ""
    practical_notes: str = ""
    people: list[RelationshipPersonProfile]


def default_relationship_profile() -> RelationshipProfile:
    return RelationshipProfile(
        relationship_mode=RelationshipMode.LONG_DISTANCE,
        currently_together=False,
        relationship_notes="Joris and Dan are in a long-distance relationship.",
        practical_notes=(
            "When apart, shared activities need to work remotely unless they say they are visiting."
        ),
        people=[
            RelationshipPersonProfile(
                user_type=UserType.JORIS,
                preferred_name="Joris",
                location="Netherlands",
                timezone="Europe/Amsterdam",
            ),
            RelationshipPersonProfile(
                user_type=UserType.DANFENG,
                preferred_name="Dan",
                location="Stockholm",
                timezone="Europe/Stockholm",
            ),
        ],
    )
