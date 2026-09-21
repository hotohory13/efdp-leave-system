import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee
from app.models.employee import Employee
from app.models.enums import EmployeeRole, OfficialDutyStatus
from app.models.misc import OfficialDuty
from app.schemas.schemas import DutyDecisionRequest, OfficialDutyCreate, OfficialDutyOut
from app.services import duty_engine

router = APIRouter(prefix="/api/official-duties", tags=["official-duties"])


@router.post("", response_model=OfficialDutyOut, status_code=201)
async def submit_duty(
    payload: OfficialDutyCreate,
    db: AsyncSession = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    try:
        duty = await duty_engine.submit_duty(
            db,
            owner=employee,
            start_date=payload.start_date,
            end_date=payload.end_date,
            destination=payload.destination,
            purpose=payload.purpose,
            is_retroactive=payload.is_retroactive,
            retro_justification=payload.retro_justification,
            evidence_url=payload.evidence_url,
            correlation_id=str(uuid.uuid4()),
        )
    except duty_engine.DutyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return duty


@router.get("/mine", response_model=list[OfficialDutyOut])
async def my_duties(db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)):
    result = await db.execute(
        select(OfficialDuty).where(OfficialDuty.owner_id == employee.id).order_by(OfficialDuty.submitted_at.desc())
    )
    return result.scalars().all()


@router.get("/queue", response_model=list[OfficialDutyOut])
async def duty_queue(db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)):
    if employee.role not in (EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN):
        return []
    query = select(OfficialDuty).where(OfficialDuty.status == OfficialDutyStatus.PENDING)
    if employee.role == EmployeeRole.HEAD_OF_DEPARTMENT:
        query = query.where(OfficialDuty.department_id == employee.department_id)
    result = await db.execute(query.order_by(OfficialDuty.submitted_at))
    return result.scalars().all()


@router.post("/{duty_id}/decide", response_model=OfficialDutyOut)
async def decide_duty(
    duty_id: int,
    payload: DutyDecisionRequest,
    db: AsyncSession = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    duty = await db.get(OfficialDuty, duty_id)
    if not duty:
        raise HTTPException(status_code=404, detail="Duty record not found")
    try:
        updated = await duty_engine.decide_duty(
            db, duty=duty, decision=payload.decision, note=payload.note, actor=employee,
            correlation_id=str(uuid.uuid4()),
        )
    except duty_engine.NotAuthorizedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except duty_engine.DutyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return updated
