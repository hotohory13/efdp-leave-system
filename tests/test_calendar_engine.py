from datetime import date

import pytest

from app.models.misc import HolidayCalendar
from app.services.calendar_engine import count_leave_days, count_working_days


@pytest.mark.asyncio
async def test_working_days_excludes_weekend(db_session):
    # 2026-01-04 is a Sunday, 2026-01-10 is the following Saturday.
    # Weekend = Friday(4)/Saturday(5) -> Fri 01-09 and Sat 01-10 excluded.
    days = await count_working_days(db_session, date(2026, 1, 4), date(2026, 1, 10))
    assert days == 5


@pytest.mark.asyncio
async def test_working_days_excludes_holiday(db_session):
    db_session.add(HolidayCalendar(holiday_date=date(2026, 1, 7), name_en="Test Holiday", name_ar="اختبار", year=2026))
    await db_session.commit()
    # Same range as above, minus the holiday on Wednesday 01-07.
    days = await count_working_days(db_session, date(2026, 1, 4), date(2026, 1, 10))
    assert days == 4


@pytest.mark.asyncio
async def test_single_day_range_is_inclusive(db_session):
    # 2026-01-04 is a Sunday (a working day).
    days = await count_working_days(db_session, date(2026, 1, 4), date(2026, 1, 4))
    assert days == 1


@pytest.mark.asyncio
async def test_single_weekend_day_counts_zero(db_session):
    # 2026-01-09 is a Friday.
    days = await count_working_days(db_session, date(2026, 1, 9), date(2026, 1, 9))
    assert days == 0


@pytest.mark.asyncio
async def test_leave_days_includes_sandwiched_weekend(db_session):
    # Thursday 2026-01-08 to Sunday 2026-01-11
    # Spans Thursday (work), Friday (weekend), Saturday (weekend), Sunday (work).
    # Sandwiched weekend (Fri & Sat) counts as leave days -> Total 4 days.
    days = await count_leave_days(db_session, date(2026, 1, 8), date(2026, 1, 11))
    assert days == 4


@pytest.mark.asyncio
async def test_leave_days_excludes_trailing_weekend(db_session):
    # Sunday 2026-01-04 to Saturday 2026-01-10
    # Weekend at the end (Fri & Sat) is not sandwiched -> 5 days.
    days = await count_leave_days(db_session, date(2026, 1, 4), date(2026, 1, 10))
    assert days == 5

