from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave import LeaveRequest
from app.models.misc import OfficialDuty


async def next_request_key(db: AsyncSession, year: int) -> str:
    """LR-2026-00042 style, sequential per year. Not perfectly race-safe
    under SQLite without a serializing transaction, which is acceptable for
    the pilot scale this system targets; PostgreSQL deployments should wrap
    the caller in SERIALIZABLE isolation if concurrent submission volume
    grows (see README -> Known Limitations)."""
    prefix = f"LR-{year}-"
    result = await db.execute(
        select(func.count()).select_from(LeaveRequest).where(LeaveRequest.request_key.like(f"{prefix}%"))
    )
    seq = result.scalar_one() + 1
    return f"{prefix}{seq:05d}"


async def next_duty_key(db: AsyncSession, year: int) -> str:
    prefix = f"OD-{year}-"
    result = await db.execute(
        select(func.count()).select_from(OfficialDuty).where(OfficialDuty.duty_key.like(f"{prefix}%"))
    )
    seq = result.scalar_one() + 1
    return f"{prefix}{seq:05d}"
