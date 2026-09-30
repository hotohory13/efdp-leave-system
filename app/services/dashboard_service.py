from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.enums import EmployeeRole, LeaveRequestStatus, OfficialDutyStatus
from app.models.leave import ApprovalStep, LeaveBalance, LeaveRequest, LeaveType
from app.models.misc import AppSetting, OfficialDuty
from app.models.org import Department


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


async def get_absent_employees_today(db: AsyncSession, target_date: date) -> list[dict]:
    """Returns list of employees who have approved leave or official duty on target_date."""
    absent_list = []

    # 1. Approved Leave Requests active on target_date
    leave_res = await db.execute(
        select(LeaveRequest, Employee, LeaveType, Department)
        .join(Employee, Employee.id == LeaveRequest.applicant_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .join(Department, Department.id == Employee.department_id)
        .where(
            LeaveRequest.status == LeaveRequestStatus.APPROVED,
            LeaveRequest.start_date <= target_date,
            LeaveRequest.end_date >= target_date,
        )
    )

    for leave, emp, lt, dept in leave_res.all():
        absent_list.append(
            {
                "employee_id": emp.id,
                "employee_name": emp.full_name_en,
                "employee_name_ar": emp.full_name_ar,
                "department_code": dept.code,
                "type_category": "Leave",
                "type_name": f"{lt.code} ({lt.name_en})",
                "start_date": leave.start_date,
                "end_date": leave.end_date,
                "reason": leave.reason,
                "status_label": "On Leave",
            }
        )

    # 2. Approved Official Duties active on target_date
    duty_res = await db.execute(
        select(OfficialDuty, Employee, Department)
        .join(Employee, Employee.id == OfficialDuty.owner_id)
        .join(Department, Department.id == OfficialDuty.department_id)
        .where(
            OfficialDuty.status == OfficialDutyStatus.APPROVED,
            OfficialDuty.start_date <= target_date,
            OfficialDuty.end_date >= target_date,
        )
    )

    for duty, emp, dept in duty_res.all():
        absent_list.append(
            {
                "employee_id": emp.id,
                "employee_name": emp.full_name_en,
                "employee_name_ar": emp.full_name_ar,
                "department_code": dept.code,
                "type_category": "Official Duty",
                "type_name": f"Duty: {duty.destination}",
                "start_date": duty.start_date,
                "end_date": duty.end_date,
                "reason": duty.purpose,
                "status_label": "On Duty",
            }
        )

    return absent_list


async def get_manager_pending_approvals(db: AsyncSession, employee: Employee) -> dict:
    """Returns pending leave requests & official duties for manager/admin approval."""
    if employee.role not in (EmployeeRole.ADMIN, EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN):
        return {"leave_queue": [], "duty_queue": [], "leave_type_lookup": {}, "employee_lookup": {}, "total_pending": 0}

    if employee.role == EmployeeRole.ADMIN:
        leave_query = select(LeaveRequest).where(
            LeaveRequest.status.in_([LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2])
        )
    else:
        stage_number = 1 if employee.role == EmployeeRole.HEAD_OF_DEPARTMENT else 2
        leave_query = (
            select(LeaveRequest)
            .join(ApprovalStep, ApprovalStep.request_id == LeaveRequest.id)
            .where(
                ApprovalStep.stage_number == LeaveRequest.current_stage,
                LeaveRequest.current_stage == stage_number,
                ApprovalStep.assigned_to_id == employee.id,
            )
        )
    leave_result = await db.execute(leave_query.order_by(LeaveRequest.submitted_at.desc()))
    leave_queue = leave_result.scalars().all()

    duty_query = select(OfficialDuty).where(OfficialDuty.status == OfficialDutyStatus.PENDING)
    if employee.role == EmployeeRole.HEAD_OF_DEPARTMENT:
        duty_query = duty_query.where(OfficialDuty.department_id == employee.department_id)
    duty_result = await db.execute(duty_query.order_by(OfficialDuty.submitted_at.desc()))
    duty_queue = duty_result.scalars().all()

    leave_types_result = await db.execute(select(LeaveType))
    leave_type_lookup = {lt.id: f"{lt.code} — {lt.name_en}" for lt in leave_types_result.scalars().all()}
    employees_result = await db.execute(select(Employee))
    employee_lookup = {e.id: e.full_name_en for e in employees_result.scalars().all()}

    return {
        "leave_queue": leave_queue,
        "duty_queue": duty_queue,
        "leave_type_lookup": leave_type_lookup,
        "employee_lookup": employee_lookup,
        "total_pending": len(leave_queue) + len(duty_queue),
    }

