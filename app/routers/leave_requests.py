import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee
from app.models.employee import Employee
from app.models.enums import EmployeeRole, LeaveRequestStatus
from app.models.leave import ApprovalStep, LeaveRequest, LeaveType
from app.schemas.schemas import LeaveDecisionRequest, LeaveRequestCreate, LeaveRequestOut
from app.services import leave_engine

router = APIRouter(prefix="/api/leave-requests", tags=["leave-requests"])


@router.post("", response_model=LeaveRequestOut, status_code=201)
async def submit_leave_request(
    payload: LeaveRequestCreate,
    db: AsyncSession = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    leave_type = await db.get(LeaveType, payload.leave_type_id)
    if not leave_type or not leave_type.is_active:
        raise HTTPException(status_code=404, detail="Leave type not found")

    try:
        request = await leave_engine.submit_leave_request(
            db,
            applicant=employee,
            leave_type=leave_type,
            start_date=payload.start_date,
            end_date=payload.end_date,
            substitute_id=payload.substitute_id,
            reason=payload.reason,
            submission_id=payload.submission_id,
            correlation_id=str(uuid.uuid4()),
        )
    except leave_engine.LeaveValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # includes InsufficientBalanceError
        raise HTTPException(status_code=422, detail=str(exc))
    return request


@router.get("/mine", response_model=list[LeaveRequestOut])
async def my_requests(db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)):
    result = await db.execute(
        select(LeaveRequest)
        .where(LeaveRequest.applicant_id == employee.id)
        .order_by(LeaveRequest.submitted_at.desc())
    )
    return result.scalars().all()


@router.get("/queue", response_model=list[LeaveRequestOut])
async def approval_queue(db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)):
    """Requests currently awaiting a decision from the caller — resolved by
    which ApprovalStep is assigned to them at the request's current stage."""
    if employee.role not in (EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN):
        return []
    stage_number = 1 if employee.role == EmployeeRole.HEAD_OF_DEPARTMENT else 2
    query = (
        select(LeaveRequest)
        .join(ApprovalStep, ApprovalStep.request_id == LeaveRequest.id)
        .where(
            ApprovalStep.stage_number == LeaveRequest.current_stage,
            LeaveRequest.current_stage == stage_number,
        )
    )
    if employee.role == EmployeeRole.ADMIN:
        query = select(LeaveRequest).where(
            LeaveRequest.status.in_([LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2])
        )
    elif employee.role == EmployeeRole.HEAD_OF_DEPARTMENT:
        query = query.where(ApprovalStep.assigned_to_id == employee.id)
    else:  # Vice Dean — faculty-wide, no department scoping
        query = query.where(ApprovalStep.assigned_to_id == employee.id)
    result = await db.execute(query.order_by(LeaveRequest.submitted_at))
    return result.scalars().all()


@router.get("/{request_id}", response_model=LeaveRequestOut)
async def get_request(
    request_id: int, db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)
):
    request = await db.get(LeaveRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    is_manager = employee.role in (EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN)
    if request.applicant_id != employee.id and not is_manager:
        raise HTTPException(status_code=403, detail="Not authorized to view this request")
    return request


@router.post("/{request_id}/decide", response_model=LeaveRequestOut)
async def decide_request(
    request_id: int,
    payload: LeaveDecisionRequest,
    db: AsyncSession = Depends(get_db),
    employee: Employee = Depends(get_current_employee),
):
    request = await db.get(LeaveRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    try:
        updated = await leave_engine.decide_step(
            db,
            leave_request=request,
            stage_number=request.current_stage,
            decision=payload.decision,
            note=payload.note,
            actor=employee,
            correlation_id=str(uuid.uuid4()),
        )
    except leave_engine.NotAuthorizedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except leave_engine.LeaveValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return updated


@router.post("/{request_id}/cancel", response_model=LeaveRequestOut)
async def cancel_request(
    request_id: int, db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)
):
    request = await db.get(LeaveRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    try:
        updated = await leave_engine.cancel_request(
            db, leave_request=request, actor=employee, correlation_id=str(uuid.uuid4())
        )
    except leave_engine.NotAuthorizedError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except leave_engine.LeaveValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return updated
