from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee, require_admin
from app.core.security import hash_password
from app.models.employee import Employee
from app.models.enums import EmploymentStatus
from app.schemas.schemas import EmployeeCreate, EmployeeOut, EmployeeUpdate
from app.services import audit

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("", response_model=list[EmployeeOut])
async def list_employees(
    department_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_employee),
):
    query = select(Employee).where(Employee.employment_status == EmploymentStatus.ACTIVE)
    if department_id:
        query = query.where(Employee.department_id == department_id)
    result = await db.execute(query.order_by(Employee.full_name_en))
    return result.scalars().all()


@router.get("/{employee_id}", response_model=EmployeeOut)
async def get_employee(
    employee_id: int, db: AsyncSession = Depends(get_db), _: Employee = Depends(get_current_employee)
):
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(
    payload: EmployeeCreate, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    existing = await db.execute(select(Employee).where(Employee.email == payload.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An employee with this email already exists")

    employee = Employee(
        employee_code=payload.employee_code,
        full_name_en=payload.full_name_en,
        full_name_ar=payload.full_name_ar,
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        department_id=payload.department_id,
        program_id=payload.program_id,
        academic_rank=payload.academic_rank,
        role=payload.role,
        supervisor_id=payload.supervisor_id,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Employee = Depends(require_admin),
):
    """Admin-only. Updates directory fields and, if `new_password` is
    provided, resets the employee's password. Every change is recorded in
    the audit log (never the password value itself)."""
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = payload.model_dump(exclude_unset=True, exclude={"new_password"})
    if "email" in data and data["email"]:
        data["email"] = data["email"].lower()
        existing = await db.execute(
            select(Employee).where(Employee.email == data["email"], Employee.id != employee_id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Another employee already uses this email")

    changed_fields = [field for field, value in data.items() if getattr(employee, field) != value]
    for field, value in data.items():
        setattr(employee, field, value)

    if payload.new_password:
        employee.hashed_password = hash_password(payload.new_password)
        changed_fields.append("password")

    if changed_fields:
        await audit.record(
            db,
            entity_type="Employee",
            entity_key=employee.employee_code,
            action="AdminUpdatedEmployee",
            resolved_actor_id=actor.id,
            details=f"Admin {actor.email} updated: {', '.join(changed_fields)}.",
        )

    await db.commit()
    await db.refresh(employee)
    return employee


@router.post("/{employee_id}/deactivate", response_model=EmployeeOut)
async def deactivate_employee(
    employee_id: int, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    """Deactivation, never deletion (FR-DIR-05) — a deleted row would orphan
    every historical request naming this person."""
    employee = await db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    employee.employment_status = EmploymentStatus.INACTIVE
    await db.commit()
    await db.refresh(employee)
    return employee
