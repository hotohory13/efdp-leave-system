"""
Attendance Tracking & PDF Reporting — server-rendered UI.

Mirrors the conventions of app/routers/web.py: session-cookie auth via
`get_current_employee_optional`, redirect (not 401) when signed out, and
all business logic delegated to app/services/attendance_service.py. Kept
as its own router (rather than folded into web.py) because it is a
self-contained module with its own PDF export endpoint.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_employee_optional
from app.core.timezone import today_local, to_local
from app.models.employee import Employee
from app.models.enums import EmployeeRole, EmploymentStatus
from app.models.org import Department
from app.services import attendance_service

router = APIRouter(include_in_schema=False)

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_name"] = settings.APP_NAME
templates.env.globals["faculty_name"] = settings.FACULTY_NAME
templates.env.globals["developer_credit"] = settings.DEVELOPER_CREDIT


def _local_time_filter(dt, fmt: str = "%I:%M %p") -> str:
    """Jinja filter: render a stored (UTC) timestamp in the Faculty's local
    timezone (settings.APP_TIMEZONE) instead of raw server/UTC time."""
    local_dt = to_local(dt)
    return local_dt.strftime(fmt) if local_dt else "—"


templates.env.filters["local_time"] = _local_time_filter


def _render(request: Request, template: str, **context):
    return templates.TemplateResponse(request, template, context)


def _require_admin_page(employee: Employee | None):
    """Returns a redirect if the caller isn't signed in / isn't an admin, else None."""
    if not employee:
        return RedirectResponse("/login", status_code=303)
    if employee.role != EmployeeRole.ADMIN:
        return RedirectResponse("/", status_code=303)
    return None


# --- Employee actions --------------------------------------------------------
@router.post("/attendance/check-in")
async def attendance_check_in(
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    try:
        await attendance_service.check_in(db, employee=employee, correlation_id=str(uuid.uuid4()))
    except attendance_service.AttendanceValidationError:
        pass
    return RedirectResponse("/", status_code=303)


@router.post("/attendance/check-out")
async def attendance_check_out(
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    try:
        await attendance_service.check_out(db, employee=employee, correlation_id=str(uuid.uuid4()))
    except attendance_service.AttendanceValidationError:
        pass
    return RedirectResponse("/", status_code=303)


@router.get("/attendance/mine")
async def attendance_mine_page(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    target_year = year or today_local().year
    records = await attendance_service.get_my_attendance(db, employee, year=target_year, month=month)
    return _render(
        request,
        "attendance_mine.html",
        user=employee,
        records=records,
        year=target_year,
        month=month,
    )


# --- Admin overview & PDF export ---------------------------------------------
@router.get("/admin/attendance")
async def admin_attendance_page(
    request: Request,
    department_id: int | None = None,
    employee_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect

    rows = await attendance_service.get_filtered_attendance(
        db,
        department_id=department_id,
        employee_id=employee_id,
        start_date=start_date,
        end_date=end_date,
    )
    summary = attendance_service.summarize(rows)

    departments_result = await db.execute(select(Department).order_by(Department.name_en))
    employees_result = await db.execute(
        select(Employee).where(Employee.employment_status == EmploymentStatus.ACTIVE).order_by(Employee.full_name_en)
    )

    return _render(
        request,
        "admin/attendance.html",
        user=employee,
        rows=rows,
        summary=summary,
        departments=departments_result.scalars().all(),
        employees=employees_result.scalars().all(),
        filters={
            "department_id": department_id,
            "employee_id": employee_id,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


@router.get("/admin/attendance/report/pdf")
async def admin_attendance_report_pdf(
    department_id: int | None = None,
    employee_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect

    pdf_bytes = await attendance_service.build_attendance_report_pdf(
        db,
        generated_by=employee,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
        employee_id=employee_id,
    )
    filename = f"EFDP-Attendance-Report-{today_local().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
