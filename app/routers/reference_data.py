from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee, require_admin
from app.models.employee import Employee
from app.models.leave import LeaveType
from app.models.misc import HolidayCalendar
from app.models.org import Department
from app.schemas.schemas import (
    DepartmentCreate,
    DepartmentOut,
    HolidayCreate,
    HolidayOut,
    LeaveTypeCreate,
    LeaveTypeOut,
    LeaveTypeUpdate,
)

router = APIRouter(prefix="/api", tags=["reference-data"])


# --- Departments -------------------------------------------------------
@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(db: AsyncSession = Depends(get_db), _: Employee = Depends(get_current_employee)):
    result = await db.execute(select(Department).order_by(Department.name_en))
    return result.scalars().all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(
    payload: DepartmentCreate, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    existing = await db.execute(select(Department).where(Department.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A department with this code already exists")
    department = Department(code=payload.code, name_en=payload.name_en, name_ar=payload.name_ar)
    db.add(department)
    await db.commit()
    await db.refresh(department)
    return department


# --- Leave types ---------------------------------------------------------
@router.get("/leave-types", response_model=list[LeaveTypeOut])
async def list_leave_types(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(get_current_employee),
):
    query = select(LeaveType)
    if not include_inactive:
        query = query.where(LeaveType.is_active.is_(True))
    result = await db.execute(query.order_by(LeaveType.code))
    return result.scalars().all()


@router.post("/leave-types", response_model=LeaveTypeOut, status_code=201)
async def create_leave_type(
    payload: LeaveTypeCreate, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    existing = await db.execute(select(LeaveType).where(LeaveType.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A leave type with this code already exists")
    leave_type = LeaveType(**payload.model_dump())
    db.add(leave_type)
    await db.commit()
    await db.refresh(leave_type)
    return leave_type


@router.patch("/leave-types/{leave_type_id}", response_model=LeaveTypeOut)
async def update_leave_type(
    leave_type_id: int,
    payload: LeaveTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _: Employee = Depends(require_admin),
):
    leave_type = await db.get(LeaveType, leave_type_id)
    if not leave_type:
        raise HTTPException(status_code=404, detail="Leave type not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(leave_type, field, value)
    await db.commit()
    await db.refresh(leave_type)
    return leave_type


# --- Holidays ------------------------------------------------------------
@router.get("/holidays", response_model=list[HolidayOut])
async def list_holidays(
    year: int | None = None, db: AsyncSession = Depends(get_db), _: Employee = Depends(get_current_employee)
):
    query = select(HolidayCalendar).order_by(HolidayCalendar.holiday_date)
    if year:
        query = query.where(HolidayCalendar.year == year)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/holidays", response_model=HolidayOut, status_code=201)
async def create_holiday(
    payload: HolidayCreate, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    existing = await db.execute(select(HolidayCalendar).where(HolidayCalendar.holiday_date == payload.holiday_date))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A holiday is already recorded on this date")
    holiday = HolidayCalendar(
        holiday_date=payload.holiday_date,
        name_en=payload.name_en,
        name_ar=payload.name_ar,
        year=payload.holiday_date.year,
    )
    db.add(holiday)
    await db.commit()
    await db.refresh(holiday)
    return holiday


@router.delete("/holidays/{holiday_id}", status_code=204)
async def delete_holiday(holiday_id: int, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)):
    holiday = await db.get(HolidayCalendar, holiday_id)
    if not holiday:
        raise HTTPException(status_code=404, detail="Holiday not found")
    await db.delete(holiday)
    await db.commit()
