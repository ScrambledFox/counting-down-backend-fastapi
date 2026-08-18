"""Seed synthetic relationship-care examples for local development only."""

import asyncio

from bson import ObjectId

from app.core.config import get_settings
from app.db.mongo_client import get_db
from app.repositories.relationship_care import (
    AgreementAcceptanceRepository,
    AgreementResponseRepository,
    AgreementRevisionRepository,
    PersonalBoundaryRepository,
    PersonalGoalRepository,
    RelationshipAgreementRepository,
    RelationshipRequestRepository,
    ensure_relationship_care_indexes,
)
from app.schemas.v1.relationship_care import AgreementCreate, FairnessType
from app.schemas.v1.user import UserType
from app.services.relationship_care import RelationshipCareService

EXAMPLES = [
    (
        "protecting-conflict",
        "Protecting us during conflict",
        "Arguments should not make either person feel that the relationship is being used "
        "as leverage.",
        "We do not threaten the relationship or personally attack each other during arguments. "
        "Either person may request a pause and commits to returning to the conversation later.",
    ),
    (
        "trust-without-surveillance",
        "Trust without surveillance",
        "Trust grows through honest conversation rather than routine inspection.",
        "We answer direct relationship-relevant questions honestly, but do not routinely inspect "
        "each other’s phones, private messages, or social interactions to prove innocence.",
    ),
    (
        "feelings-and-outcomes",
        "Feelings matter without deciding the outcome",
        "Emotions deserve care without automatically overruling either person’s choices.",
        "We take each other’s emotions seriously while recognizing that disappointment, fear, "
        "jealousy, or anger do not automatically mean the other person’s decision was wrong.",
    ),
    (
        "shared-repair",
        "Shared repair",
        "Repair works best when responsibility is shared rather than carried by the hurt person.",
        "When one of us causes harm, we acknowledge our part and actively participate in repair.",
    ),
    (
        "equal-consideration",
        "Equal consideration",
        "Different needs can coexist with equal respect.",
        "Different needs may justify different accommodations, but asymmetric arrangements are "
        "discussed and freely agreed rather than assumed.",
    ),
]


async def seed() -> None:
    settings = get_settings()
    if settings.app_env.lower() == "prod":
        raise RuntimeError("Relationship-care examples must never be seeded in production")

    db = get_db()
    await ensure_relationship_care_indexes(db)
    service = RelationshipCareService(
        boundary_repo=PersonalBoundaryRepository(db),
        request_repo=RelationshipRequestRepository(db),
        goal_repo=PersonalGoalRepository(db),
        agreement_repo=RelationshipAgreementRepository(db),
        revision_repo=AgreementRevisionRepository(db),
        acceptance_repo=AgreementAcceptanceRepository(db),
        response_repo=AgreementResponseRepository(db),
    )
    collection = db[settings.relationship_agreements_collection_name]
    created = 0
    for seed_key, title, why_it_matters, agreement_text in EXAMPLES:
        if await collection.count_documents({"seed_key": seed_key}, limit=1):
            continue
        draft = await service.create_agreement(
            AgreementCreate(
                title=title,
                why_it_matters=why_it_matters,
                agreement_text=agreement_text,
                fairness_type=FairnessType.SYMMETRIC,
            ),
            UserType.JORIS,
        )
        agreement_id = str(draft.agreement.id)
        revision_id = str(draft.current_revision.revision.id)
        await service.propose_agreement(agreement_id, UserType.JORIS)
        await service.accept_revision(revision_id, UserType.JORIS)
        await service.accept_revision(revision_id, UserType.DANFENG)
        await collection.update_one(
            {"_id": ObjectId(agreement_id)}, {"$set": {"seed_key": seed_key}}
        )
        created += 1
    print(f"Created {created} relationship-care examples")


if __name__ == "__main__":
    asyncio.run(seed())
