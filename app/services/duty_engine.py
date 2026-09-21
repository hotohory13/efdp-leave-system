"""
Official duty (مأمورية) engine.

Per OD-01 (attendance limited to advance registration + corrections, no
daily check-in/out register) and OD-13 option 2 (adopted): a retroactive
registration is a duty record submitted late with a written justification,
not a separate entity. Consumes no leave entitlement — it is not leave.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.employee import Employee
from app.models.enums import EmployeeRole, OfficialDutyStatus
from app.models.misc import OfficialDuty
from app.services import audit, notifications
from app.services.calendar_engine import count_working_days
from app.services.keys import next_duty_key


class DutyValidationError(Exception):
    pass


class NotAuthorizedError(Exception):
    pass


async def submit_duty(
    db: AsyncSession,
    *,
    owner: Employee,
    start_date: date,
    end_date: date,
    destination: str,
    purpose: str,
    is_retroactive: bool,
    retro_justification: str | None,
    evidence_url: str | None,
    correlation_id: str,
) -> OfficialDuty:
    if end_date < start_date:
        raise DutyValidationError("End date must not be before the start date.")
    if not destination.strip():
        raise DutyValidationError("Destination is required.")
    if is_retroactive and (
        not retro_justification or len(retro_justification.strip()) < settings.RETRO_JUSTIFICATION_MIN_LENGTH
    ):
        raise DutyValidationError(
            f"A retroactive registration needs a justification of at least "
            f"{settings.RETRO_JUSTIFICATION_MIN_LENGTH} characters (OD-13)."
        )

    working_days = await count_working_days(db, start_date, end_date)
    duty_key = await next_duty_key(db, start_date.year)

    duty = OfficialDuty(
        duty_key=duty_key,
        owner_id=owner.id,
        department_id=owner.department_id,
        start_date=start_date,
        end_date=end_date,
        duty_year=start_date.year,
        working_days=working_days,
        destination=destination.strip(),
        purpose=purpose.strip(),
        evidence_url=evidence_url,
        is_retroactive=is_retroactive,
        retro_justification=retro_justification.strip() if retro_justification else None,
        status=OfficialDutyStatus.PENDING,
    )
    db.add(duty)
    await db.flush()

    await audit.record(
        db,
        entity_type="OfficialDuty",
        entity_key=duty_key,
        action="Submitted",
        resolved_actor_id=owner.id,
        correlation_id=correlation_id,
    )

    head_result = await db.execute(
        select(Employee).where(
            Employee.department_id == owner.department_id,
            Employee.role == EmployeeRole.HEAD_OF_DEPARTMENT,
        )
    )
    head = head_result.scalars().first()
    if head:
        await notifications.send(
            db,
            recipient_email=head.email,
            subject=f"Official duty {duty_key} awaiting your review",
            body=f"{owner.full_name_en} registered a duty to {destination} ({start_date} to {end_date}).",
            template_key="duty_pending",
        )

    await db.commit()
    await db.refresh(duty)
    return duty


async def decide_duty(
    db: AsyncSession, *, duty: OfficialDuty, decision: str, note: str | None, actor: Employee, correlation_id: str
) -> OfficialDuty:
    if actor.role not in (EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN):
        raise NotAuthorizedError("Only a Head of Department, Vice Dean, or Administrator may decide this.")
    if duty.status != OfficialDutyStatus.PENDING:
        raise DutyValidationError(f"This duty is already {duty.status.value}.")
    if decision not in ("Approved", "Rejected"):
        raise DutyValidationError("Decision must be 'Approved' or 'Rejected'.")
    if decision == "Rejected" and (not note or len(note.strip()) < settings.REJECTION_NOTE_MIN_LENGTH):
        raise DutyValidationError(
            f"A rejection must include a reason of at least {settings.REJECTION_NOTE_MIN_LENGTH} characters."
        )

    duty.status = OfficialDutyStatus.APPROVED if decision == "Approved" else OfficialDutyStatus.REJECTED
    duty.approved_by_id = actor.id
    duty.decision_note = note.strip() if note else None

    await audit.record(
        db,
        entity_type="OfficialDuty",
        entity_key=duty.duty_key,
        action=decision,
        resolved_actor_id=actor.id,
        correlation_id=correlation_id,
        details=note,
    )

    owner = await db.get(Employee, duty.owner_id)
    if owner:
        await notifications.send(
            db,
            recipient_email=owner.email,
            subject=f"Update on official duty {duty.duty_key}",
            body=f"Your official duty registration was {decision.lower()}." + (f" Reason: {note}" if note else ""),
            template_key=f"duty_{decision.lower()}",
        )

    await db.commit()
    await db.refresh(duty)
    return duty
