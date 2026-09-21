"""
Local-timezone helpers.

Attendance timestamps (`check_in`/`check_out`) are stored in UTC — that
part is correct and should stay that way. What was missing is a
conversion step before anything gets shown to a user or bucketed into a
calendar day: without it, both display and the "which day is this
check-in for" logic silently used the server's own timezone (UTC),
not the Faculty's (`settings.APP_TIMEZONE`, Africa/Cairo).
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

LOCAL_TZ = ZoneInfo(settings.APP_TIMEZONE)


def to_local(dt: datetime | None) -> datetime | None:
    """Convert a stored timestamp to the Faculty's local timezone for display.
    Treats naive datetimes as UTC (SQLite drops tzinfo on round-trip)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_local() -> date:
    """Today's calendar date in the Faculty's local timezone — use this
    (not `date.today()`) for anything that decides which day an
    attendance record belongs to, so a check-in just after local midnight
    isn't misfiled under the previous UTC day."""
    return datetime.now(LOCAL_TZ).date()
