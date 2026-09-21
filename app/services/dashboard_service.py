from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.enums import LeaveRequestStatus
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType
from app.models.misc import AppSetting


async def get_my_balances(db: AsyncSession, employee: Employee, year: int | None = None) -> list[dict]:
    target_year = year or date.today().year
    result = await db.execute(
        select(LeaveBalance, LeaveType)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .where(LeaveBalance.employee_id == employee.id, LeaveBalance.year == target_year)
    )
    balances = []
    for balance, leave_type in result.all():
        balances.append(
            {
                "leave_type_id": leave_type.id,
                "leave_type_code": leave_type.code,
                "leave_type_name_en": leave_type.name_en,
                "leave_type_name_ar": leave_type.name_ar,
                "year": balance.year,
                "entitled_days": balance.entitled_days,
                "used_days": balance.used_days,
                "pending_days": balance.pending_days,
                "remaining_days": balance.remaining_days,
            }
        )
    return balances


async def get_dashboard_summary(db: AsyncSession, employee: Employee) -> dict:
    result = await db.execute(select(AppSetting).where(AppSetting.key.like("metric:%")))
    metrics = {row.key.replace("metric:", ""): row.value for row in result.scalars().all()}

    my_pending = await db.execute(
        select(LeaveRequest).where(
            LeaveRequest.applicant_id == employee.id,
            LeaveRequest.status.in_([LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2]),
        )
    )
    return {
        "faculty_metrics": metrics,
        "my_pending_requests": len(my_pending.scalars().all()),
    }


async def get_recent_requests(db: AsyncSession, employee: Employee, limit: int = 5) -> list[LeaveRequest]:
    result = await db.execute(
        select(LeaveRequest)
        .where(LeaveRequest.applicant_id == employee.id)
        .order_by(LeaveRequest.submitted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
