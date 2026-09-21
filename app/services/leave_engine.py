"""
Leave request workflow engine.

Encodes, in one place:
  * BR-03 — a Teaching Assistant must name a substitute; no other role
    requires one.
  * "No self-substitution" and "end date >= start date" — the same checks
    the source design put in the SharePoint list validation formula
    (Part 3 §5.1), now enforced in the service layer.
  * The two-stage approval chain resolved by OD-02 in Part 3 §5.3:
    stage 1 Head of Department, stage 2 Vice Dean.
  * The reservation model (ADR-07) via app.services.balance_engine.
  * Idempotent submission (ADR-08): a repeated call with the same
    submission_id returns the original request rather than creating a
    duplicate — the double-tap protection described in Formula-Changes.md.
  * OD-11 — the substitute is notified with a right to object; this is
    never a blocking approval step.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.employee import Employee
from app.models.enums import ApprovalStepStatus, EmployeeRole, LeaveRequestStatus
from app.models.leave import ApprovalRoute, ApprovalStep, LeaveRequest, LeaveType
from app.services import audit, balance_engine, notifications
from app.services.calendar_engine import count_leave_days, count_working_days
from app.services.keys import next_request_key


class LeaveValidationError(Exception):
    pass


class NotAuthorizedError(Exception):
    pass


STAGE_NAMES = {1: "HeadOfDepartment", 2: "ViceDean"}


async def _resolve_assignee(db: AsyncSession, *, stage_name: str, department_id: int) -> Employee | None:
    """Find who is assigned to a stage, honouring any active delegation
    (AR-07 / EFSOP_ApprovalDelegations) covering today."""
    if stage_name == "HeadOfDepartment":
        result = await db.execute(
            select(Employee).where(
                Employee.department_id == department_id,
                Employee.role == EmployeeRole.HEAD_OF_DEPARTMENT,
                Employee.employment_status == "Active",
            )
        )
    else:  # ViceDean — faculty-wide, no department scoping (Formula-Changes.md §A.5 parallel)
        result = await db.execute(
            select(Employee).where(
                Employee.role == EmployeeRole.VICE_DEAN,
                Employee.employment_status == "Active",
            )
        )
    approver = result.scalars().first()
    if approver is None:
        return None

    from app.models.leave import ApprovalDelegation  # local import avoids a circular import at module load

    today = date.today()
    delegation_result = await db.execute(
        select(ApprovalDelegation).where(
            ApprovalDelegation.from_employee_id == approver.id,
            ApprovalDelegation.is_active.is_(True),
            ApprovalDelegation.start_date <= today,
            ApprovalDelegation.end_date >= today,
        )
    )
    delegation = delegation_result.scalars().first()
    if delegation is not None:
        delegate = await db.get(Employee, delegation.to_employee_id)
        return delegate or approver
    return approver


async def _get_route(db: AsyncSession, stage_number: int) -> ApprovalRoute | None:
    result = await db.execute(select(ApprovalRoute).where(ApprovalRoute.stage_number == stage_number))
    return result.scalar_one_or_none()


async def submit_leave_request(
    db: AsyncSession,
    *,
    applicant: Employee,
    leave_type: LeaveType,
    start_date: date,
    end_date: date,
    substitute_id: int | None,
    reason: str,
    submission_id: str,
    correlation_id: str,
) -> LeaveRequest:
    # --- Idempotency (ADR-08) ------------------------------------------------
    existing = await db.execute(select(LeaveRequest).where(LeaveRequest.submission_id == submission_id))
    existing_request = existing.scalar_one_or_none()
    if existing_request is not None:
        return existing_request

    # --- Validation ------------------------------------------------------
    if end_date < start_date:
        raise LeaveValidationError("End date must not be before the start date.")

    if applicant.role == EmployeeRole.TEACHING_ASSISTANT and not substitute_id:
        raise LeaveValidationError("Teaching Assistants must name a substitute colleague (BR-03).")

    if substitute_id and substitute_id == applicant.id:
        raise LeaveValidationError("The substitute cannot be the applicant themselves.")

    working_days = await count_leave_days(db, start_date, end_date)
    if working_days <= 0:
        raise LeaveValidationError("The selected range contains no working days.")
    if working_days > leave_type.max_consecutive_days:
        raise LeaveValidationError(
            f"{leave_type.name_en} may not exceed {leave_type.max_consecutive_days} consecutive working day(s)."
        )
    if len(reason.strip()) < 5:
        raise LeaveValidationError("Please provide a reason (at least 5 characters).")

    applicant_overlap = await db.execute(
        select(LeaveRequest).where(
            LeaveRequest.applicant_id == applicant.id,
            LeaveRequest.status.in_([
                LeaveRequestStatus.PENDING_STAGE_1,
                LeaveRequestStatus.PENDING_STAGE_2,
                LeaveRequestStatus.APPROVED,
            ]),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
        )
    )
    if applicant_overlap.scalars().first() is not None:
        raise LeaveValidationError("You already have an active or pending leave request during the selected period.")

    substitute = None
    if substitute_id:
        substitute = await db.get(Employee, substitute_id)
        if substitute is None:
            raise LeaveValidationError("Selected substitute was not found.")

        substitute_overlap = await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.applicant_id == substitute_id,
                LeaveRequest.status.in_([
                    LeaveRequestStatus.PENDING_STAGE_1,
                    LeaveRequestStatus.PENDING_STAGE_2,
                    LeaveRequestStatus.APPROVED,
                ]),
                LeaveRequest.start_date <= end_date,
                LeaveRequest.end_date >= start_date,
            )
        )
        if substitute_overlap.scalars().first() is not None:
            raise LeaveValidationError(
                "Selected substitute colleague has an active or pending leave request during the selected period."
            )

    # --- Balance reservation ------------------------------------------------
    year = start_date.year
    balance = await balance_engine.get_or_create_balance(db, employee=applicant, leave_type=leave_type, year=year)
    balance_engine.reserve(balance, working_days)

    secondary_balance = None
    if leave_type.deducts_from_annual:
        annual_type_result = await db.execute(select(LeaveType).where(LeaveType.code == "اعتيادي"))
        annual_type = annual_type_result.scalar_one_or_none()
        if annual_type and annual_type.id != leave_type.id:
            secondary_balance = await balance_engine.get_or_create_balance(
                db, employee=applicant, leave_type=annual_type, year=year
            )
            balance_engine.reserve(secondary_balance, working_days)

    # --- Create the request row ------------------------------------------
    request_key = await next_request_key(db, year)
    leave_request = LeaveRequest(
        request_key=request_key,
        submission_id=submission_id,
        applicant_id=applicant.id,
        applicant_role=applicant.role,
        department_id=applicant.department_id,
        leave_type_id=leave_type.id,
        start_date=start_date,
        end_date=end_date,
        request_year=year,
        working_days=working_days,
        substitute_id=substitute_id,
        reason=reason.strip(),
        status=LeaveRequestStatus.PENDING_STAGE_1,
        current_stage=1,
        correlation_id=correlation_id,
    )
    db.add(leave_request)
    await db.flush()

    # --- Two approval-step rows (OD-02 as resolved, Part 3 §5.3) ------------
    now = datetime.now(timezone.utc)
    for stage_number in (1, 2):
        route = await _get_route(db, stage_number)
        sla_hours = route.sla_hours if route else (
            settings.APPROVAL_STAGE_1_SLA_HOURS if stage_number == 1 else settings.APPROVAL_STAGE_2_SLA_HOURS
        )
        escalation_hours = route.escalation_hours if route else settings.APPROVAL_ESCALATION_HOURS
        stage_name = STAGE_NAMES[stage_number]
        assignee = await _resolve_assignee(db, stage_name=stage_name, department_id=applicant.department_id)
        step = ApprovalStep(
            request_id=leave_request.id,
            stage_number=stage_number,
            stage_name=stage_name,
            assigned_to_id=assignee.id if assignee else None,
            status=ApprovalStepStatus.PENDING,
            sla_due_at=now + timedelta(hours=sla_hours),
            escalation_due_at=now + timedelta(hours=escalation_hours),
        )
        db.add(step)

    await audit.record(
        db,
        entity_type="LeaveRequest",
        entity_key=request_key,
        action="Submitted",
        resolved_actor_id=applicant.id,
        correlation_id=correlation_id,
        details=f"{leave_type.code}, {start_date} to {end_date}, {working_days} working day(s).",
    )

    # --- Notifications (non-blocking) ---------------------------------------
    stage1 = await db.execute(select(ApprovalStep).where(ApprovalStep.request_id == leave_request.id, ApprovalStep.stage_number == 1))
    stage1_step = stage1.scalar_one()
    if stage1_step.assigned_to_id:
        approver = await db.get(Employee, stage1_step.assigned_to_id)
        if approver:
            await notifications.send(
                db,
                recipient_email=approver.email,
                subject=f"Leave request {request_key} awaiting your approval",
                body=(
                    f"{applicant.full_name_en} submitted a {leave_type.name_en} request "
                    f"({start_date} to {end_date}, {working_days} working day(s)). "
                    f"Reason: {reason.strip()}"
                ),
                template_key="leave_stage1_pending",
            )

    if substitute is not None:
        leave_request.substitute_notified_at = now
        await notifications.send(
            db,
            recipient_email=substitute.email,
            subject=f"You were named as substitute on {request_key}",
            body=(
                f"{applicant.full_name_en} named you as substitute for a leave request "
                f"from {start_date} to {end_date}. If you were not consulted, reply to "
                f"this notification or contact your Head of Department (OD-11: notification "
                f"with a right to object — this does not block the request)."
            ),
            template_key="substitute_notified",
        )

    await db.commit()
    await db.refresh(leave_request)
    return leave_request


async def decide_step(
    db: AsyncSession,
    *,
    leave_request: LeaveRequest,
    stage_number: int,
    decision: str,  # "Approved" | "Rejected"
    note: str | None,
    actor: Employee,
    correlation_id: str,
) -> LeaveRequest:
    if decision not in ("Approved", "Rejected"):
        raise LeaveValidationError("Decision must be 'Approved' or 'Rejected'.")

    if leave_request.current_stage != stage_number:
        raise LeaveValidationError(
            f"This request is currently awaiting stage {leave_request.current_stage}, not stage {stage_number}."
        )
    if leave_request.status not in (LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2):
        raise LeaveValidationError(f"This request is already {leave_request.status.value} and cannot be decided.")

    step_result = await db.execute(
        select(ApprovalStep).where(
            ApprovalStep.request_id == leave_request.id, ApprovalStep.stage_number == stage_number
        )
    )
    step = step_result.scalar_one()

    if actor.role != EmployeeRole.ADMIN and step.assigned_to_id != actor.id:
        raise NotAuthorizedError("You are not the assigned approver for this stage.")

    if decision == "Rejected" and (not note or len(note.strip()) < settings.REJECTION_NOTE_MIN_LENGTH):
        raise LeaveValidationError(
            f"A rejection must include a reason of at least {settings.REJECTION_NOTE_MIN_LENGTH} characters."
        )

    now = datetime.now(timezone.utc)
    step.status = ApprovalStepStatus.APPROVED if decision == "Approved" else ApprovalStepStatus.REJECTED
    step.decision_at = now
    step.decision_note = note.strip() if note else None

    leave_type = await db.get(LeaveType, leave_request.leave_type_id)
    applicant = await db.get(Employee, leave_request.applicant_id)
    balance = await balance_engine.get_or_create_balance(
        db, employee=applicant, leave_type=leave_type, year=leave_request.request_year
    )
    secondary_balance = None
    if leave_type.deducts_from_annual:
        annual_type_result = await db.execute(select(LeaveType).where(LeaveType.code == "اعتيادي"))
        annual_type = annual_type_result.scalar_one_or_none()
        if annual_type and annual_type.id != leave_type.id:
            secondary_balance = await balance_engine.get_or_create_balance(
                db, employee=applicant, leave_type=annual_type, year=leave_request.request_year
            )

    if decision == "Rejected":
        leave_request.status = LeaveRequestStatus.REJECTED
        leave_request.decision_note = note.strip() if note else None
        balance_engine.release_pending(balance, leave_request.working_days)
        if secondary_balance:
            balance_engine.release_pending(secondary_balance, leave_request.working_days)
        recipient = applicant
        message = f"Your leave request {leave_request.request_key} was rejected. Reason: {note}"
    elif stage_number == 1:
        leave_request.status = LeaveRequestStatus.PENDING_STAGE_2
        leave_request.current_stage = 2
        recipient = None
        message = None
    else:  # stage 2 approved -> final approval, commit the reservation (ADR-07)
        leave_request.status = LeaveRequestStatus.APPROVED
        leave_request.decision_note = note.strip() if note else leave_request.decision_note
        balance_engine.commit_pending_to_used(balance, leave_request.working_days)
        if secondary_balance:
            balance_engine.commit_pending_to_used(secondary_balance, leave_request.working_days)
        recipient = applicant
        message = f"Your leave request {leave_request.request_key} was approved."

    await audit.record(
        db,
        entity_type="LeaveRequest",
        entity_key=leave_request.request_key,
        action=f"Stage{stage_number}{decision}",
        resolved_actor_id=actor.id,
        correlation_id=correlation_id,
        details=note,
    )

    if recipient:
        await notifications.send(
            db,
            recipient_email=recipient.email,
            subject=f"Update on leave request {leave_request.request_key}",
            body=message,
            template_key=f"leave_{decision.lower()}",
        )
    elif leave_request.status == LeaveRequestStatus.PENDING_STAGE_2:
        stage2 = await db.execute(
            select(ApprovalStep).where(ApprovalStep.request_id == leave_request.id, ApprovalStep.stage_number == 2)
        )
        stage2_step = stage2.scalar_one()
        if stage2_step.assigned_to_id:
            vice_dean = await db.get(Employee, stage2_step.assigned_to_id)
            if vice_dean:
                await notifications.send(
                    db,
                    recipient_email=vice_dean.email,
                    subject=f"Leave request {leave_request.request_key} awaiting your approval",
                    body=(
                        f"Approved by Head of Department. {applicant.full_name_en}'s "
                        f"{leave_type.name_en} request ({leave_request.start_date} to "
                        f"{leave_request.end_date}) now awaits your decision."
                    ),
                    template_key="leave_stage2_pending",
                )

    await db.commit()
    await db.refresh(leave_request)
    return leave_request


async def cancel_request(
    db: AsyncSession, *, leave_request: LeaveRequest, actor: Employee, correlation_id: str
) -> LeaveRequest:
    if actor.id != leave_request.applicant_id and actor.role != EmployeeRole.ADMIN:
        raise NotAuthorizedError("Only the applicant (or an administrator) can cancel this request.")
    if leave_request.status not in (LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2):
        raise LeaveValidationError(f"Requests that are already {leave_request.status.value} cannot be cancelled.")

    leave_type = await db.get(LeaveType, leave_request.leave_type_id)
    applicant = await db.get(Employee, leave_request.applicant_id)
    balance = await balance_engine.get_or_create_balance(
        db, employee=applicant, leave_type=leave_type, year=leave_request.request_year
    )
    balance_engine.release_pending(balance, leave_request.working_days)
    if leave_type.deducts_from_annual:
        annual_type_result = await db.execute(select(LeaveType).where(LeaveType.code == "اعتيادي"))
        annual_type = annual_type_result.scalar_one_or_none()
        if annual_type and annual_type.id != leave_type.id:
            secondary_balance = await balance_engine.get_or_create_balance(
                db, employee=applicant, leave_type=annual_type, year=leave_request.request_year
            )
            balance_engine.release_pending(secondary_balance, leave_request.working_days)

    leave_request.status = LeaveRequestStatus.CANCELLED
    await audit.record(
        db,
        entity_type="LeaveRequest",
        entity_key=leave_request.request_key,
        action="Cancelled",
        resolved_actor_id=actor.id,
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(leave_request)
    return leave_request
