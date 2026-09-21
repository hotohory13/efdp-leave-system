"""
Working-day calculation.

Mirrors the business rule discussed at length in Part 1 §12 (OD-04): the
working-day count is wrong around every public holiday until the holiday
calendar is complete. This engine is correct given whatever holidays are
loaded — it is the *data*, not the arithmetic, that the source documents
flag as incomplete (see docs/BUSINESS_RULES.md).
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.misc import HolidayCalendar


async def get_holiday_set(db: AsyncSession, years: set[int]) -> set[date]:
    if not years:
        return set()
    result = await db.execute(select(HolidayCalendar.holiday_date).where(HolidayCalendar.year.in_(years)))
    return {row[0] for row in result.all()}


async def count_working_days(db: AsyncSession, start: date, end: date) -> int:
    """Inclusive of both start and end. Excludes configured weekend days
    (default Friday/Saturday) and any date present in the holiday calendar."""
    if end < start:
        raise ValueError("end date must not be before start date")

    years = {y for y in range(start.year, end.year + 1)}
    holidays = await get_holiday_set(db, years)
    weekend_days = set(settings.weekend_days)

    count = 0
    current = start
    while current <= end:
        if current.weekday() not in weekend_days and current not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


async def count_leave_days(db: AsyncSession, start: date, end: date) -> int:
    """Calculates leave days for a requested range [start, end].
    Excludes public holidays. Excludes weekend days UNLESS the weekend days
    are sandwiched between working leave days within the requested date range
    (e.g., Thursday through Sunday includes Friday & Saturday as leave days)."""
    if end < start:
        raise ValueError("end date must not be before start date")

    years = {y for y in range(start.year, end.year + 1)}
    holidays = await get_holiday_set(db, years)
    weekend_days = set(settings.weekend_days)

    all_dates = []
    current = start
    while current <= end:
        all_dates.append(current)
        current += timedelta(days=1)

    working_dates = {
        d for d in all_dates if d.weekday() not in weekend_days and d not in holidays
    }

    if not working_dates:
        return 0

    first_working = min(working_dates)
    last_working = max(working_dates)

    count = 0
    for d in all_dates:
        if d in holidays:
            continue
        if d.weekday() in weekend_days:
            if first_working < d < last_working:
                count += 1
        else:
            count += 1

    return count

