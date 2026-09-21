"""
Server-rendered UI (session-cookie based).

Every page a signed-in user sees lives here. This router never
re-implements business logic — it collects form input, calls the same
service-layer functions the JSON API uses (`leave_engine`, `duty_engine`,
`dashboard_service`), and renders a template with the result. The one
exception is Admin panel reference-data CRUD (departments, leave types,
holidays, settings, employee creation), which is simple enough that it
talks to the ORM directly rather than round-tripping through its own API
client.

Auth model: a page route depends on `get_current_employee_optional` and
redirects to `/login` itself rather than raising a 401 — a browser tab
should land on the login page, not a JSON error.
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_employee_optional
from app.core.security import create_access_token, hash_password, verify_password
from app.core.timezone import today_local, to_local
from app.models.employee import Employee
from app.models.enums import EmployeeRole, EmploymentStatus, LeaveRequestStatus, OfficialDutyStatus
from app.models.leave import ApprovalStep, LeaveRequest, LeaveType
from app.models.misc import AppSetting, AuditLog, HolidayCalendar, NotificationLog, OfficialDuty
from app.models.org import Department
from app.services import attendance_service, audit, dashboard_service, duty_engine, leave_engine, report_pdf

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

MANAGER_ROLES = (EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN)


def _render(request: Request, template: str, **context):
    return templates.TemplateResponse(request, template, context)


# --- Auth --------------------------------------------------------------
@router.get("/login")
async def login_page(request: Request, employee: Employee | None = Depends(get_current_employee_optional)):
    if employee:
        return RedirectResponse("/", status_code=303)
    return _render(request, "login.html")


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Employee).where(Employee.email == email.strip().lower()))
    employee = result.scalar_one_or_none()
    if not employee or not verify_password(password, employee.hashed_password) or not employee.is_active:
        return _render(request, "login.html", error="Incorrect email/password, or the account is inactive.", email=email)

    token = create_access_token(subject=employee.email, extra_claims={"role": employee.role.value})
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("efdp_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 8)
    return response


@router.post("/logout")
async def logout_submit():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("efdp_token")
    return response


# --- Dashboard -----------------------------------------------------------
@router.get("/")
async def dashboard_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    year = today_local().year
    balances = await dashboard_service.get_my_balances(db, employee, year)
    summary = await dashboard_service.get_dashboard_summary(db, employee)
    recent_requests = await dashboard_service.get_recent_requests(db, employee)
    today_attendance = await attendance_service.get_today_attendance(db, employee)
    return _render(
        request,
        "dashboard.html",
        user=employee,
        year=year,
        balances=balances,
        summary=summary,
        recent_requests=recent_requests,
        today_attendance=today_attendance,
        today=today_local(),
    )


# --- Leave requests --------------------------------------------------------
@router.get("/leave/new")
async def leave_new_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    leave_types_result = await db.execute(select(LeaveType).where(LeaveType.is_active.is_(True)).order_by(LeaveType.code))
    colleagues_result = await db.execute(
        select(Employee)
        .where(Employee.employment_status == EmploymentStatus.ACTIVE, Employee.id != employee.id)
        .order_by(Employee.full_name_en)
    )
    return _render(
        request,
        "leave_new.html",
        user=employee,
        leave_types=leave_types_result.scalars().all(),
        colleagues=colleagues_result.scalars().all(),
    )


@router.post("/leave/new")
async def leave_new_submit(
    request: Request,
    leave_type_id: int = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    substitute_id: str = Form(""),
    reason: str = Form(...),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    leave_type = await db.get(LeaveType, leave_type_id)
    if not leave_type or not leave_type.is_active:
        return RedirectResponse("/leave/new", status_code=303)
    try:
        await leave_engine.submit_leave_request(
            db,
            applicant=employee,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            substitute_id=int(substitute_id) if substitute_id else None,
            reason=reason,
            submission_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
        )
    except Exception as exc:
        leave_types_result = await db.execute(select(LeaveType).where(LeaveType.is_active.is_(True)))
        colleagues_result = await db.execute(
            select(Employee).where(Employee.employment_status == EmploymentStatus.ACTIVE, Employee.id != employee.id)
        )
        return _render(
            request,
            "leave_new.html",
            user=employee,
            error=str(exc),
            leave_types=leave_types_result.scalars().all(),
            colleagues=colleagues_result.scalars().all(),
        )
    return RedirectResponse("/leave/mine", status_code=303)


@router.get("/leave/mine")
async def leave_mine_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    result = await db.execute(
        select(LeaveRequest).where(LeaveRequest.applicant_id == employee.id).order_by(LeaveRequest.submitted_at.desc())
    )
    requests_list = result.scalars().all()

    leave_types_result = await db.execute(select(LeaveType))
    leave_type_lookup = {lt.id: f"{lt.code} — {lt.name_en}" for lt in leave_types_result.scalars().all()}
    employees_result = await db.execute(select(Employee))
    employee_lookup = {e.id: e.full_name_en for e in employees_result.scalars().all()}

    return _render(
        request,
        "leave_mine.html",
        user=employee,
        requests=requests_list,
        leave_type_lookup=leave_type_lookup,
        employee_lookup=employee_lookup,
    )


@router.post("/leave/{request_id}/cancel")
async def leave_cancel_submit(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    leave_request = await db.get(LeaveRequest, request_id)
    if leave_request:
        try:
            await leave_engine.cancel_request(
                db, leave_request=leave_request, actor=employee, correlation_id=str(uuid.uuid4())
            )
        except Exception:
            pass
    return RedirectResponse("/leave/mine", status_code=303)


# --- Official duties (مأمورية) ---------------------------------------------
@router.get("/duties/new")
async def duties_new_page(request: Request, employee: Employee | None = Depends(get_current_employee_optional)):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    return _render(request, "duties_new.html", user=employee)


@router.post("/duties/new")
async def duties_new_submit(
    request: Request,
    start_date: date = Form(...),
    end_date: date = Form(...),
    destination: str = Form(...),
    purpose: str = Form(...),
    is_retroactive: str = Form(""),
    retro_justification: str = Form(""),
    evidence_url: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    try:
        await duty_engine.submit_duty(
            db,
            owner=employee,
            start_date=start_date,
            end_date=end_date,
            destination=destination,
            purpose=purpose,
            is_retroactive=bool(is_retroactive),
            retro_justification=retro_justification or None,
            evidence_url=evidence_url or None,
            correlation_id=str(uuid.uuid4()),
        )
    except Exception as exc:
        return _render(request, "duties_new.html", user=employee, error=str(exc))
    return RedirectResponse("/duties/mine", status_code=303)


@router.get("/duties/mine")
async def duties_mine_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    result = await db.execute(
        select(OfficialDuty).where(OfficialDuty.owner_id == employee.id).order_by(OfficialDuty.submitted_at.desc())
    )
    return _render(request, "duties_mine.html", user=employee, duties=result.scalars().all())


# --- Approval queue (leave requests + official duties) ----------------------
@router.get("/approvals")
async def approvals_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee:
        return RedirectResponse("/login", status_code=303)
    if employee.role not in MANAGER_ROLES:
        return RedirectResponse("/", status_code=303)

    # Leave-request queue — mirrors app/routers/leave_requests.py::approval_queue
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
    leave_result = await db.execute(leave_query.order_by(LeaveRequest.submitted_at))
    leave_queue = leave_result.scalars().all()

    duty_query = select(OfficialDuty).where(OfficialDuty.status == OfficialDutyStatus.PENDING)
    if employee.role == EmployeeRole.HEAD_OF_DEPARTMENT:
        duty_query = duty_query.where(OfficialDuty.department_id == employee.department_id)
    duty_result = await db.execute(duty_query.order_by(OfficialDuty.submitted_at))
    duty_queue = duty_result.scalars().all()

    leave_types_result = await db.execute(select(LeaveType))
    leave_type_lookup = {lt.id: f"{lt.code} — {lt.name_en}" for lt in leave_types_result.scalars().all()}
    employees_result = await db.execute(select(Employee))
    employee_lookup = {e.id: e.full_name_en for e in employees_result.scalars().all()}

    return _render(
        request,
        "approvals.html",
        user=employee,
        leave_queue=leave_queue,
        duty_queue=duty_queue,
        leave_type_lookup=leave_type_lookup,
        employee_lookup=employee_lookup,
        rejection_note_min_length=settings.REJECTION_NOTE_MIN_LENGTH,
    )


@router.post("/approvals/leave/{request_id}/decide")
async def approvals_leave_decide(
    request_id: int,
    decision: str = Form(...),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee or employee.role not in MANAGER_ROLES:
        return RedirectResponse("/login", status_code=303)
    leave_request = await db.get(LeaveRequest, request_id)
    if leave_request:
        try:
            await leave_engine.decide_step(
                db,
                leave_request=leave_request,
                stage_number=leave_request.current_stage,
                decision=decision,
                note=note or None,
                actor=employee,
                correlation_id=str(uuid.uuid4()),
            )
        except Exception:
            pass
    return RedirectResponse("/approvals", status_code=303)


@router.post("/approvals/duty/{duty_id}/decide")
async def approvals_duty_decide(
    duty_id: int,
    decision: str = Form(...),
    note: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if not employee or employee.role not in MANAGER_ROLES:
        return RedirectResponse("/login", status_code=303)
    duty = await db.get(OfficialDuty, duty_id)
    if duty:
        try:
            await duty_engine.decide_duty(
                db, duty=duty, decision=decision, note=note or None, actor=employee, correlation_id=str(uuid.uuid4())
            )
        except Exception:
            pass
    return RedirectResponse("/approvals", status_code=303)


# --- Admin panel -----------------------------------------------------------
def _require_admin_page(employee: Employee | None):
    """Returns a redirect if the caller isn't signed in / isn't an admin, else None."""
    if not employee:
        return RedirectResponse("/login", status_code=303)
    if employee.role != EmployeeRole.ADMIN:
        return RedirectResponse("/", status_code=303)
    return None


@router.get("/admin")
async def admin_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    counts = {}
    for label, model in (
        ("departments", Department),
        ("employees", Employee),
        ("leave_types", LeaveType),
        ("holidays", HolidayCalendar),
    ):
        result = await db.execute(select(model))
        counts[label] = len(result.scalars().all())
    return _render(request, "admin/index.html", user=employee, counts=counts)


@router.get("/admin/reports/export-pdf")
async def admin_export_pdf(
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    pdf_bytes = await report_pdf.build_admin_report_pdf(db, generated_by=employee, year=year)
    report_year = year or date.today().year
    filename = f"EFDP-Report-{report_year}-{date.today().isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/departments")
async def admin_departments_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(Department).order_by(Department.name_en))
    return _render(request, "admin/departments.html", user=employee, departments=result.scalars().all())


@router.post("/admin/departments")
async def admin_departments_create(
    code: str = Form(...),
    name_en: str = Form(...),
    name_ar: str = Form(...),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    existing = await db.execute(select(Department).where(Department.code == code.strip().upper()))
    if not existing.scalar_one_or_none():
        db.add(Department(code=code.strip().upper(), name_en=name_en.strip(), name_ar=name_ar.strip()))
        await db.commit()
    return RedirectResponse("/admin/departments", status_code=303)


@router.get("/admin/leave-types")
async def admin_leave_types_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(LeaveType).order_by(LeaveType.code))
    return _render(request, "admin/leave_types.html", user=employee, leave_types=result.scalars().all())


@router.post("/admin/leave-types")
async def admin_leave_types_create(
    code: str = Form(...),
    name_en: str = Form(...),
    name_ar: str = Form(...),
    annual_cap: int = Form(...),
    max_consecutive_days: int = Form(...),
    deducts_from_annual: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    existing = await db.execute(select(LeaveType).where(LeaveType.code == code.strip()))
    if not existing.scalar_one_or_none():
        db.add(
            LeaveType(
                code=code.strip(),
                name_en=name_en.strip(),
                name_ar=name_ar.strip(),
                annual_cap=annual_cap,
                max_consecutive_days=max_consecutive_days,
                deducts_from_annual=bool(deducts_from_annual),
                is_active=True,
            )
        )
        await db.commit()
    return RedirectResponse("/admin/leave-types", status_code=303)


@router.post("/admin/leave-types/{leave_type_id}/toggle")
async def admin_leave_types_toggle(
    leave_type_id: int,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    leave_type = await db.get(LeaveType, leave_type_id)
    if leave_type:
        leave_type.is_active = not leave_type.is_active
        await db.commit()
    return RedirectResponse("/admin/leave-types", status_code=303)


@router.get("/admin/employees")
async def admin_employees_page(
    request: Request,
    success: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(Employee).order_by(Employee.full_name_en))
    departments_result = await db.execute(select(Department).order_by(Department.name_en))
    return _render(
        request,
        "admin/employees.html",
        user=employee,
        employees=result.scalars().all(),
        departments=departments_result.scalars().all(),
        roles=list(EmployeeRole),
        success=success,
        error=error,
    )


@router.post("/admin/employees")
async def admin_employees_create(
    request: Request,
    employee_code: str = Form(...),
    full_name_en: str = Form(...),
    full_name_ar: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    department_id: int = Form(...),
    role: str = Form(...),
    academic_rank: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    existing = await db.execute(select(Employee).where(Employee.email == email.strip().lower()))
    if not existing.scalar_one_or_none():
        db.add(
            Employee(
                employee_code=employee_code.strip(),
                full_name_en=full_name_en.strip(),
                full_name_ar=full_name_ar.strip(),
                email=email.strip().lower(),
                hashed_password=hash_password(password),
                department_id=department_id,
                academic_rank=academic_rank or None,
                role=EmployeeRole(role),
            )
        )
        await db.commit()
    return RedirectResponse("/admin/employees", status_code=303)


@router.post("/admin/employees/{employee_id}/edit")
async def admin_employees_edit(
    employee_id: int,
    full_name_en: str = Form(...),
    email: str = Form(...),
    department_id: int = Form(...),
    role: str = Form(...),
    is_active: str = Form(""),
    new_password: str = Form(""),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect

    target = await db.get(Employee, employee_id)
    if not target:
        return RedirectResponse("/admin/employees?error=Employee+not+found", status_code=303)

    normalized_email = email.strip().lower()
    existing = await db.execute(select(Employee).where(Employee.email == normalized_email, Employee.id != employee_id))
    if existing.scalar_one_or_none():
        return RedirectResponse("/admin/employees?error=Another+employee+already+uses+that+email", status_code=303)

    changed_fields = []
    if target.full_name_en != full_name_en.strip():
        changed_fields.append("name")
    if target.email != normalized_email:
        changed_fields.append("email")
    if target.department_id != department_id:
        changed_fields.append("department")
    if target.role.value != role:
        changed_fields.append("role")

    target.full_name_en = full_name_en.strip()
    target.email = normalized_email
    target.department_id = department_id
    target.role = EmployeeRole(role)
    new_status = EmploymentStatus.ACTIVE if is_active else EmploymentStatus.INACTIVE
    if target.employment_status != new_status:
        changed_fields.append("status")
    target.employment_status = new_status

    password_changed = bool(new_password.strip())
    if password_changed:
        target.hashed_password = hash_password(new_password.strip())
        changed_fields.append("password")

    if changed_fields:
        await audit.record(
            db,
            entity_type="Employee",
            entity_key=target.employee_code,
            action="AdminUpdatedEmployee",
            resolved_actor_id=employee.id,
            details=f"Admin {employee.email} updated: {', '.join(changed_fields)}.",
        )

    await db.commit()
    message = "Employee updated successfully."
    if password_changed:
        message = "Employee updated and password reset successfully."
    return RedirectResponse(f"/admin/employees?success={message.replace(' ', '+')}", status_code=303)


@router.post("/admin/employees/{employee_id}/deactivate")
async def admin_employees_deactivate(
    employee_id: int,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    target = await db.get(Employee, employee_id)
    if target:
        target.employment_status = EmploymentStatus.INACTIVE
        await db.commit()
    return RedirectResponse("/admin/employees", status_code=303)


@router.get("/admin/holidays")
async def admin_holidays_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(HolidayCalendar).order_by(HolidayCalendar.holiday_date))
    return _render(request, "admin/holidays.html", user=employee, holidays=result.scalars().all())


@router.post("/admin/holidays")
async def admin_holidays_create(
    holiday_date: date = Form(...),
    name_en: str = Form(...),
    name_ar: str = Form(...),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    existing = await db.execute(select(HolidayCalendar).where(HolidayCalendar.holiday_date == holiday_date))
    if not existing.scalar_one_or_none():
        db.add(HolidayCalendar(holiday_date=holiday_date, name_en=name_en.strip(), name_ar=name_ar.strip(), year=holiday_date.year))
        await db.commit()
    return RedirectResponse("/admin/holidays", status_code=303)


@router.post("/admin/holidays/{holiday_id}/delete")
async def admin_holidays_delete(
    holiday_id: int,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    holiday = await db.get(HolidayCalendar, holiday_id)
    if holiday:
        await db.delete(holiday)
        await db.commit()
    return RedirectResponse("/admin/holidays", status_code=303)


@router.get("/admin/settings")
async def admin_settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(AppSetting).where(~AppSetting.key.like("metric:%")).order_by(AppSetting.key))
    return _render(request, "admin/settings.html", user=employee, app_settings=result.scalars().all())


@router.post("/admin/settings/{key}")
async def admin_settings_update(
    key: str,
    value: str = Form(...),
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        await db.commit()
    return RedirectResponse("/admin/settings", status_code=303)


@router.get("/admin/audit-log")
async def admin_audit_log_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(200))
    return _render(request, "admin/audit_log.html", user=employee, entries=result.scalars().all())


@router.get("/admin/notifications")
async def admin_notifications_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    employee: Employee | None = Depends(get_current_employee_optional),
):
    if (redirect := _require_admin_page(employee)) is not None:
        return redirect
    result = await db.execute(select(NotificationLog).order_by(NotificationLog.occurred_at.desc()).limit(200))
    return _render(request, "admin/notifications.html", user=employee, entries=result.scalars().all())
