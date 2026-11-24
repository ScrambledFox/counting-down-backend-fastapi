"""Create every MongoDB index the application relies on.

All index helpers are idempotent. They run from ``scripts/ensure_indexes.py`` at deploy time and,
unless ``ENSURE_INDEXES_ON_STARTUP`` is false, during web startup.
"""

from app.models.mongo import AsyncDB
from app.repositories.airport import ensure_airport_indexes
from app.repositories.image_jobs import ImageJobRepository
from app.repositories.mediation import ensure_mediation_indexes
from app.repositories.relationship_care import ensure_relationship_care_indexes
from app.repositories.relationship_profile import ensure_relationship_profile_indexes
from app.repositories.xiaobao import ensure_xiaobao_indexes
from app.repositories.xiaobao_push import ensure_xiaobao_push_indexes
from app.repositories.xiaobao_routine import ensure_xiaobao_routine_indexes


async def ensure_all_indexes(db: AsyncDB) -> None:
    await ensure_mediation_indexes(db)
    await ensure_airport_indexes(db)
    await ensure_relationship_care_indexes(db)
    await ensure_relationship_profile_indexes(db)
    # Routine indexes depend on the Xiao Bao message collections existing first.
    await ensure_xiaobao_indexes(db)
    await ensure_xiaobao_routine_indexes(db)
    await ensure_xiaobao_push_indexes(db)
    await ImageJobRepository(db).ensure_indexes()
