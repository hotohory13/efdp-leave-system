"""
Leave balance engine — the reservation model (ADR-07).

`pending_days` is reserved at submission. It becomes `used_days` only at
final approval, and is released (subtracted back out) on rejection or
cancellation. `entitled - used - pending >= 0` is enforced on every mutating
call here — the application-layer equivalent of the SharePoint list
validation formula's overdraft constraint (Part 3 §5.2).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.leave import LeaveBalance, LeaveType


class InsufficientBalanceError(Exception):
    pass


async def get_or_create_balance(
    db: AsyncSession, *, employee: Employee, leave_type: LeaveType, year: int
) -> LeaveBalance:
    result = await db.execute(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.year == year,
        )
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        balance = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            year=year,
            entitled_days=leave_type.annual_cap,
            used_days=0,
            pending_days=0,
        )
        db.add(balance)
        await db.flush()
    return balance


def reserve(balance: LeaveBalance, days: int) -> None:
    if balance.used_days + balance.pending_days + days > balance.entitled_days:
        raise InsufficientBalanceError(
            f"Requested {days} day(s) exceeds remaining balance "
            f"({balance.remaining_days} of {balance.entitled_days} remaining)."
        )
    balance.pending_days += days


def release_pending(balance: LeaveBalance, days: int) -> None:
    balance.pending_days = max(0, balance.pending_days - days)


def commit_pending_to_used(balance: LeaveBalance, days: int) -> None:
    balance.pending_days = max(0, balance.pending_days - days)
    balance.used_days += days
