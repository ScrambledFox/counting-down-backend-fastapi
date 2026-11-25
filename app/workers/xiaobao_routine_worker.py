from typing import Any, cast

from app.core import logging
from app.core.config import get_settings
from app.core.logging import error_fields
from app.integrations.openai_client import OpenAIClient
from app.models.mongo import AsyncDB
from app.repositories.relationship_care import (
    AgreementAcceptanceRepository,
    AgreementResponseRepository,
    AgreementRevisionRepository,
    PersonalBoundaryRepository,
    PersonalGoalRepository,
    RelationshipAgreementRepository,
    RelationshipRequestRepository,
)
from app.repositories.relationship_profile import RelationshipProfileRepository
from app.repositories.todo import TodoRepository
from app.repositories.xiaobao import (
    XiaoBaoConversationRepository,
    XiaoBaoMessageRepository,
)
from app.repositories.xiaobao_routine import (
    XiaoBaoRoutineRepository,
    XiaoBaoRoutineRunRepository,
)
from app.schemas.v1.xiaobao_routine import XiaoBaoRoutineKind, XiaoBaoRoutineRunStatus
from app.services.relationship_care import RelationshipCareService
from app.services.relationship_profile import RelationshipProfileService
from app.services.todo import TodoService
from app.services.xiaobao_context import RelationshipContextService
from app.services.xiaobao_routine_execution import XiaoBaoRoutineExecutionService
from app.workers.job_runner import JobResult

settings = get_settings()
logger = logging.get_logger(__name__)


async def _finish_terminal_reminder_failure(
    routines: XiaoBaoRoutineRepository, failed_run: Any | None
) -> None:
    if not failed_run or failed_run.status != XiaoBaoRoutineRunStatus.FAILED:
        return
    routine = await routines.get_for_execution(failed_run.routine_id)
    if (
        routine
        and routine.kind == XiaoBaoRoutineKind.REMINDER
        and routine.committed_delivery_pending_run_id is None
    ):
        await routines.finish_one_time_failure(
            failed_run.routine_id,
            failed_run.owner_user_type,
            revision=failed_run.routine_revision,
        )


def build_routine_execution_service(
    db: AsyncDB,
) -> tuple[
    XiaoBaoRoutineExecutionService,
    XiaoBaoRoutineRepository,
    XiaoBaoRoutineRunRepository,
]:
    routines = XiaoBaoRoutineRepository(db)
    runs = XiaoBaoRoutineRunRepository(db)
    todos = TodoService(TodoRepository(db))
    relationship_care = RelationshipCareService(
        PersonalBoundaryRepository(db),
        RelationshipRequestRepository(db),
        PersonalGoalRepository(db),
        RelationshipAgreementRepository(db),
        AgreementRevisionRepository(db),
        AgreementAcceptanceRepository(db),
        AgreementResponseRepository(db),
    )
    context = RelationshipContextService(
        relationship_care,
        todos,
        cast(Any, None),  # build_for_routine deliberately has no mediation dependency or query.
        RelationshipProfileService(RelationshipProfileRepository(db)),
    )
    return (
        XiaoBaoRoutineExecutionService(
            routines,
            runs,
            XiaoBaoConversationRepository(db),
            XiaoBaoMessageRepository(db),
            context,
            OpenAIClient(),
        ),
        routines,
        runs,
    )


async def process_one_xiaobao_routine_work_item(
    service: XiaoBaoRoutineExecutionService,
    routines: XiaoBaoRoutineRepository,
    runs: XiaoBaoRoutineRunRepository,
) -> JobResult:
    """Repair or execute at most one routine run.

    A failed repair keeps its back-off and the call continues with unrelated work, but the call
    then reports ``FAILED`` so the failure is counted.
    """
    repair_candidates = await routines.list_committed_delivery_repairs(
        limit=settings.xiaobao_routine_materialize_batch_size
    )
    # The repair batch is bounded, but every durable delivery barrier must be excluded from
    # ordinary claim/exhaustion paths, including barriers beyond this sweep's repair batch.
    guarded_routine_ids = await routines.list_committed_delivery_guarded_routine_ids()
    repair_failed = False
    for routine in repair_candidates:
        run_id = routine.committed_delivery_pending_run_id
        if not run_id:
            continue
        repair = await runs.claim_delivery_repair(
            run_id, lease_seconds=settings.xiaobao_routine_lease_seconds
        )
        if not repair:
            continue
        try:
            await service.repair_committed_delivery(repair)
            # An earlier repair in this call may have failed; report it rather than hide it.
            return JobResult.FAILED if repair_failed else JobResult.PROCESSED
        except Exception as exc:
            logger.error(
                "Xiao Bao committed routine delivery repair failed",
                extra={
                    "event": "job_item_failed",
                    "job_kind": "routine",
                    "routine_id": repair.routine_id,
                    **error_fields(exc),
                },
            )
            await runs.mark_failed_or_retry(repair, type(exc).__name__)
            repair_failed = True
            # Keep this routine's durable barrier and continue with unrelated work. Its failed
            # repair receives available_at backoff and cannot be reclaimed in a tight loop.
            continue

    await runs.fail_exhausted_stale(excluded_routine_ids=guarded_routine_ids)
    for failed_run in await runs.list_terminal_failures(
        limit=settings.xiaobao_routine_materialize_batch_size
    ):
        await _finish_terminal_reminder_failure(routines, failed_run)
    run = await runs.claim_next(
        lease_seconds=settings.xiaobao_routine_lease_seconds,
        excluded_routine_ids=guarded_routine_ids,
    )
    if not run:
        return JobResult.FAILED if repair_failed else JobResult.IDLE
    try:
        await service.process(run)
    except Exception as exc:
        logger.error(
            "Xiao Bao routine execution failed",
            extra={
                "event": "job_item_failed",
                "job_kind": "routine",
                "routine_id": run.routine_id,
                **error_fields(exc),
            },
        )
        failed = await runs.mark_failed_or_retry(run, type(exc).__name__)
        await _finish_terminal_reminder_failure(routines, failed)
        return JobResult.FAILED
    return JobResult.FAILED if repair_failed else JobResult.PROCESSED
