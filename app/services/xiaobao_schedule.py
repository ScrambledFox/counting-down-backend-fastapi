from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.schemas.v1.xiaobao_routine import (
    XiaoBaoRoutineFrequency,
    XiaoBaoRoutineSchedule,
)


def _valid_local_candidates(local_naive: datetime, timezone: ZoneInfo) -> list[datetime]:
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = local_naive.replace(tzinfo=timezone, fold=fold)
        utc_candidate = candidate.astimezone(UTC)
        round_trip = utc_candidate.astimezone(timezone).replace(tzinfo=None)
        if round_trip == local_naive:
            candidates[utc_candidate] = candidate
    return [candidates[key] for key in sorted(candidates)]


def resolve_local_occurrence(local_naive: datetime, timezone: ZoneInfo) -> datetime:
    """Resolve one wall-clock occurrence, once across folds and forward across gaps."""
    candidate = local_naive
    for _ in range(181):
        valid = _valid_local_candidates(candidate, timezone)
        if valid:
            # During a fall-back fold choose the first instant, so the local occurrence runs once.
            return min(valid, key=lambda item: item.astimezone(UTC))
        candidate += timedelta(minutes=1)
    raise ValueError("Could not resolve local schedule time")


def _local_datetime(day: date, local_time: str) -> datetime:
    hour, minute = (int(part) for part in local_time.split(":"))
    return datetime.combine(day, time(hour=hour, minute=minute))


def one_time_scheduled_at(schedule: XiaoBaoRoutineSchedule) -> datetime:
    if schedule.frequency != XiaoBaoRoutineFrequency.ONCE or schedule.local_date is None:
        raise ValueError("A one-time schedule with local_date is required")
    timezone = ZoneInfo(schedule.timezone)
    local_naive = _local_datetime(schedule.local_date, schedule.local_time)
    valid = _valid_local_candidates(local_naive, timezone)
    if not valid:
        raise ValueError("One-time reminder local time does not exist in its timezone")
    return min(valid, key=lambda item: item.astimezone(UTC)).astimezone(UTC)


def next_scheduled_at(schedule: XiaoBaoRoutineSchedule, *, after: datetime) -> datetime:
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    after = after.astimezone(UTC)
    if schedule.frequency == XiaoBaoRoutineFrequency.ONCE:
        occurrence = one_time_scheduled_at(schedule)
        if occurrence <= after:
            raise ValueError("One-time schedule must be in the future")
        return occurrence
    timezone = ZoneInfo(schedule.timezone)
    local_after = after.astimezone(timezone)
    for offset in range(0, 371):
        day = local_after.date() + timedelta(days=offset)
        if (
            schedule.frequency == XiaoBaoRoutineFrequency.WEEKLY
            and day.weekday() not in schedule.weekdays
        ):
            continue
        occurrence = resolve_local_occurrence(_local_datetime(day, schedule.local_time), timezone)
        occurrence_utc = occurrence.astimezone(UTC)
        if occurrence_utc > after:
            return occurrence_utc
    raise ValueError("Could not find the next schedule occurrence")


def local_schedule_snapshot(scheduled_for: datetime, timezone_name: str) -> str:
    timezone = ZoneInfo(timezone_name)
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=UTC)
    return scheduled_for.astimezone(timezone).isoformat(timespec="minutes")
