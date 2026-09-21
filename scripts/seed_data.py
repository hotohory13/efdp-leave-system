"""
EFDP seed script — the provisioning-script replacement.

Parses the original `.xlsx` workbooks (copied unmodified into this
directory from the source EFSOP archive) and upserts them into the
database, matched on each sheet's stated business key so the script is
safe to re-run: an existing key is updated, a new key is created,
unchanged rows are left alone.

Usage:
    python -m scripts.seed_data                 # reference data only
    python -m scripts.seed_data --demo           # + demo employees/logins (dev/local ONLY)

Import order matters and is enforced here: Departments and Leave Types and
Holidays and Settings (any order, no cross-dependencies) THEN Employees
(validated against department codes) THEN, only with --demo, balances.

See docs/BUSINESS_RULES.md for every assumption this script encodes.
"""
import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, init_models  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.enums import EmployeeRole, EmploymentStatus  # noqa: E402
from app.models.leave import ApprovalRoute, LeaveBalance, LeaveType  # noqa: E402
from app.models.misc import AppSetting, HolidayCalendar  # noqa: E402
from app.models.org import Department  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("efdp.seed")

SCRIPTS_DIR = Path(__file__).resolve().parent

ROLE_MAP = {
    "Teaching Assistant": EmployeeRole.TEACHING_ASSISTANT,
    "Staff": EmployeeRole.STAFF,
    "Head of Department": EmployeeRole.HEAD_OF_DEPARTMENT,
    "Vice Dean": EmployeeRole.VICE_DEAN,
    "System Administrator": EmployeeRole.ADMIN,
}


def _read_sheet(path: Path, sheet_name: str) -> list[dict]:
    """Reads a sheet into a list of {header: value} dicts, skipping the
    header row. Trailing ' *' (required-column marker) is stripped from
    header names so `Title *` and `Title` both key as `Title`."""
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        logger.warning("Sheet %s not found in %s — skipping.", sheet_name, path.name)
        return []
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip().rstrip(" *").strip() if h is not None else "" for h in rows[0]]
    records = []
    for row in rows[1:]:
        if row is None or all(v is None for v in row):
            continue
        record = dict(zip(headers, row))
        records.append(record)
    return records


def _yes_no(value, default: bool | None = False) -> bool | None:
    if value is None:
        return default
    return str(value).strip().lower() == "yes"


async def seed_departments(db):
    records = _read_sheet(SCRIPTS_DIR / "EFDP-Departments.xlsx", "Departments")
    count = 0
    for r in records:
        code = str(r["Title"]).strip()
        result = await db.execute(select(Department).where(Department.code == code))
        dept = result.scalar_one_or_none()
        if dept is None:
            dept = Department(code=code)
            db.add(dept)
        dept.name_en = r.get("NameEn") or dept.code
        dept.name_ar = r.get("NameAr") or dept.code
        dept.is_active = _yes_no(r.get("IsActive"), True)
        count += 1
    await db.flush()
    logger.info("Departments: %d row(s) upserted.", count)


async def seed_leave_types(db):
    records = _read_sheet(SCRIPTS_DIR / "EFDP-LeaveTypes.xlsx", "LeaveTypes")
    count = 0
    for r in records:
        code = str(r["Title"]).strip()
        result = await db.execute(select(LeaveType).where(LeaveType.code == code))
        lt = result.scalar_one_or_none()
        if lt is None:
            lt = LeaveType(code=code)
            db.add(lt)
        lt.name_en = r.get("NameEn") or code
        lt.name_ar = r.get("NameAr") or code
        lt.annual_cap = int(r.get("AnnualCap") or 0)
        lt.max_consecutive_days = int(r.get("MaxConsecutiveDays") or lt.annual_cap or 1)
        # OD-03: workbook may leave DeductsFromAnnual blank ("Unconfirmed"). Fall back to the
        # global config default, not a hardcoded True/False — see docs/BUSINESS_RULES.md.
        lt.deducts_from_annual = _yes_no(r.get("DeductsFromAnnual"), settings.CASUAL_LEAVE_DEDUCTS_FROM_ANNUAL)
        lt.is_active = _yes_no(r.get("IsActive"), True)
        count += 1
    await db.flush()
    logger.info("Leave types: %d row(s) upserted.", count)


async def seed_holidays(db):
    records = _read_sheet(SCRIPTS_DIR / "EFDP-Holidays.xlsx", "Holidays")
    count = 0
    for r in records:
        raw_date = r.get("HolidayDate")
        if isinstance(raw_date, datetime):
            holiday_date = raw_date.date()
        elif isinstance(raw_date, date):
            holiday_date = raw_date
        else:
            holiday_date = date.fromisoformat(str(raw_date))
        result = await db.execute(select(HolidayCalendar).where(HolidayCalendar.holiday_date == holiday_date))
        holiday = result.scalar_one_or_none()
        if holiday is None:
            holiday = HolidayCalendar(holiday_date=holiday_date)
            db.add(holiday)
        holiday.name_en = r.get("NameEn") or ""
        holiday.name_ar = r.get("NameAr") or ""
        holiday.year = int(r.get("HolidayYear") or holiday_date.year)
        count += 1
    await db.flush()
    logger.info("Holidays: %d row(s) upserted.", count)


async def seed_settings(db):
    records = _read_sheet(SCRIPTS_DIR / "EFDP-Settings.xlsx", "Settings")
    count = 0
    for r in records:
        key = str(r["Title"]).strip()
        result = await db.execute(select(AppSetting).where(AppSetting.key == key))
        setting = result.scalar_one_or_none()
        if setting is None:
            setting = AppSetting(key=key)
            db.add(setting)
        setting.value = str(r.get("SettingValue") or "")
        setting.description = r.get("Description")
        count += 1
    await db.flush()
    logger.info("Settings: %d row(s) upserted.", count)


async def seed_approval_routes(db):
    """OD-02 as resolved in Part 3 §5.3: two stages, config not code."""
    routes = [
        (1, "HeadOfDepartment", EmployeeRole.HEAD_OF_DEPARTMENT, settings.APPROVAL_STAGE_1_SLA_HOURS),
        (2, "ViceDean", EmployeeRole.VICE_DEAN, settings.APPROVAL_STAGE_2_SLA_HOURS),
    ]
    for stage_number, stage_name, role, sla_hours in routes:
        result = await db.execute(select(ApprovalRoute).where(ApprovalRoute.stage_number == stage_number))
        route = result.scalar_one_or_none()
        if route is None:
            route = ApprovalRoute(stage_number=stage_number)
            db.add(route)
        route.stage_name = stage_name
        route.role_required = role
        route.sla_hours = sla_hours
        route.escalation_hours = settings.APPROVAL_ESCALATION_HOURS
    await db.flush()
    logger.info("Approval routes: 2 row(s) upserted.")


async def seed_employees(db, *, sheet_name: str, default_password: str | None) -> list[Employee]:
    """Shared by the real `Employees` sheet (normally empty by design — see
    docs/BUSINESS_RULES.md) and, with --demo, the `Example` sheet."""
    records = _read_sheet(SCRIPTS_DIR / "EFDP-Employees.xlsx", sheet_name)
    created: list[Employee] = []
    for r in records:
        email = str(r.get("UniversityEmail") or "").strip().lower()
        if not email:
            continue
        dept_code = str(r.get("Department") or "").strip()
        dept_result = await db.execute(select(Department).where(Department.code == dept_code))
        department = dept_result.scalar_one_or_none()
        if department is None:
            logger.warning("Skipping %s: department code %r not found. Import departments first.", email, dept_code)
            continue

        role_label = str(r.get("Role") or "").strip()
        role = ROLE_MAP.get(role_label)
        if role is None:
            logger.warning("Skipping %s: unrecognised role %r.", email, role_label)
            continue

        result = await db.execute(select(Employee).where(Employee.email == email))
        employee = result.scalar_one_or_none()
        is_new = employee is None
        if employee is None:
            password = default_password or f"Welcome@{r.get('EmployeeID') or 'EFDP'}"
            employee = Employee(email=email, hashed_password=hash_password(password))
            if is_new and default_password is None:
                logger.info("Created %s with temporary password %r — must be reset on first login.", email, password)
            db.add(employee)

        employee.employee_code = str(r.get("EmployeeID") or email.split("@")[0])
        employee.full_name_en = str(r.get("Title") or email)
        employee.full_name_ar = str(r.get("Title") or email)
        employee.department_id = department.id
        employee.academic_rank = r.get("AcademicRank")
        employee.role = role
        employee.employment_status = (
            EmploymentStatus.ACTIVE if str(r.get("Status") or "Active").strip() == "Active" else EmploymentStatus.INACTIVE
        )

        await db.flush()

        entitlement = r.get("AnnualEntitlement")
        year = int(r.get("BalanceYear") or date.today().year)
        if entitlement is not None:
            annual_result = await db.execute(select(LeaveType).where(LeaveType.code == "اعتيادي"))
            annual_type = annual_result.scalar_one_or_none()
            if annual_type:
                balance_result = await db.execute(
                    select(LeaveBalance).where(
                        LeaveBalance.employee_id == employee.id,
                        LeaveBalance.leave_type_id == annual_type.id,
                        LeaveBalance.year == year,
                    )
                )
                balance = balance_result.scalar_one_or_none()
                if balance is None:
                    balance = LeaveBalance(employee_id=employee.id, leave_type_id=annual_type.id, year=year)
                    db.add(balance)
                balance.entitled_days = float(entitlement)
                balance.used_days = float(r.get("AnnualUsed") or 0)
                balance.pending_days = float(r.get("AnnualPending") or 0)

        created.append(employee)
    await db.flush()
    logger.info("Employees (%s sheet): %d row(s) upserted.", sheet_name, len(created))
    return created


async def seed_demo_admin(db) -> None:
    """A single break-glass administrator account for local/dev use only —
    the real Employees sheet never contains one by default (see
    docs/BUSINESS_RULES.md). NEVER run --demo against a production database."""
    departments_result = await db.execute(select(Department).order_by(Department.id))
    department = departments_result.scalars().first()
    if department is None:
        logger.warning("No department found — cannot create demo admin.")
        return
    result = await db.execute(select(Employee).where(Employee.email == "admin@efdp.local"))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = Employee(
            employee_code="ADMIN-0001",
            full_name_en="EFDP Administrator",
            full_name_ar="مسؤول النظام",
            email="admin@efdp.local",
            hashed_password=hash_password("Admin@12345"),
            department_id=department.id,
            role=EmployeeRole.ADMIN,
        )
        db.add(admin)
        await db.flush()
        logger.info("Demo admin created: admin@efdp.local / Admin@12345 — CHANGE THIS before any real deployment.")


async def _verify_directory_health(db) -> None:
    """Mirrors 05-Verify.ps1 from the original design: warns (does not
    fail) if any active department lacks exactly one active Head of
    Department, or if there isn't exactly one active Vice Dean."""
    departments_result = await db.execute(select(Department).where(Department.is_active.is_(True)))
    for department in departments_result.scalars().all():
        heads_result = await db.execute(
            select(Employee).where(
                Employee.department_id == department.id,
                Employee.role == EmployeeRole.HEAD_OF_DEPARTMENT,
                Employee.employment_status == EmploymentStatus.ACTIVE,
            )
        )
        heads = heads_result.scalars().all()
        if len(heads) == 0:
            logger.warning("Department %s has NO active Head of Department — its requests will stall silently.", department.code)
        elif len(heads) > 1:
            logger.warning("Department %s has %d active Heads of Department — expected exactly 1.", department.code, len(heads))

    vice_deans_result = await db.execute(
        select(Employee).where(Employee.role == EmployeeRole.VICE_DEAN, Employee.employment_status == EmploymentStatus.ACTIVE)
    )
    vice_deans = vice_deans_result.scalars().all()
    if len(vice_deans) == 0:
        logger.warning("There is NO active Vice Dean — every request will stall at stage 2.")
    elif len(vice_deans) > 1:
        logger.warning("There are %d active Vice Deans — expected exactly 1.", len(vice_deans))


async def run(demo: bool) -> None:
    await init_models()
    async with AsyncSessionLocal() as db:
        await seed_departments(db)
        await seed_leave_types(db)
        await seed_holidays(db)
        await seed_settings(db)
        await seed_approval_routes(db)
        await db.commit()

        # Real employee data (normally an empty sheet by design).
        await seed_employees(db, sheet_name="Employees", default_password=None)
        await db.commit()

        if demo:
            logger.warning("--demo: seeding sample staff from the Example sheet and a break-glass admin. DEV/LOCAL ONLY.")
            await seed_employees(db, sheet_name="Example", default_password="Passw0rd!")
            await seed_demo_admin(db)
            await db.commit()

        await _verify_directory_health(db)

    logger.info("Seed complete.")


def main():
    parser = argparse.ArgumentParser(description="EFDP seed script")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Also seed sample staff (Example sheet, password 'Passw0rd!') and a break-glass admin "
        "(admin@efdp.local / Admin@12345). DEV/LOCAL ONLY — never run against production.",
    )
    args = parser.parse_args()
    asyncio.run(run(demo=args.demo))


if __name__ == "__main__":
    main()
