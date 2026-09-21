import uuid
from datetime import date

import pytest

from app.models.enums import LeaveRequestStatus
from app.services import leave_engine


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_ta_without_substitute_is_rejected(db_session, reference_data):
    with pytest.raises(leave_engine.LeaveValidationError):
        await leave_engine.submit_leave_request(
            db_session,
            applicant=reference_data["ta"],
            leave_type=reference_data["annual"],
            start_date=date(2026, 1, 4),
            end_date=date(2026, 1, 5),
            substitute_id=None,
            reason="Personal matter",
            submission_id=_uid(),
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_full_approval_flow_commits_balance(db_session, reference_data):
    request = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),  # Sunday
        end_date=date(2026, 1, 5),  # Monday -> 2 working days
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=_uid(),
        correlation_id=_uid(),
    )
    assert request.status == LeaveRequestStatus.PENDING_STAGE_1
    assert request.working_days == 2

    stage1 = await leave_engine.decide_step(
        db_session,
        leave_request=request,
        stage_number=1,
        decision="Approved",
        note=None,
        actor=reference_data["hod"],
        correlation_id=_uid(),
    )
    assert stage1.status == LeaveRequestStatus.PENDING_STAGE_2
    assert stage1.current_stage == 2

    stage2 = await leave_engine.decide_step(
        db_session,
        leave_request=stage1,
        stage_number=2,
        decision="Approved",
        note="Enjoy",
        actor=reference_data["vice_dean"],
        correlation_id=_uid(),
    )
    assert stage2.status == LeaveRequestStatus.APPROVED

    from app.services import balance_engine

    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    assert balance.used_days == 2
    assert balance.pending_days == 0


@pytest.mark.asyncio
async def test_rejection_releases_reservation(db_session, reference_data):
    request = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=_uid(),
        correlation_id=_uid(),
    )
    updated = await leave_engine.decide_step(
        db_session,
        leave_request=request,
        stage_number=1,
        decision="Rejected",
        note="Insufficient documentation provided",
        actor=reference_data["hod"],
        correlation_id=_uid(),
    )
    assert updated.status == LeaveRequestStatus.REJECTED

    from app.services import balance_engine

    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    assert balance.pending_days == 0
    assert balance.used_days == 0


@pytest.mark.asyncio
async def test_rejection_requires_note(db_session, reference_data):
    request = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=_uid(),
        correlation_id=_uid(),
    )
    with pytest.raises(leave_engine.LeaveValidationError):
        await leave_engine.decide_step(
            db_session,
            leave_request=request,
            stage_number=1,
            decision="Rejected",
            note="too short",
            actor=reference_data["hod"],
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_only_assigned_approver_may_decide(db_session, reference_data):
    request = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=_uid(),
        correlation_id=_uid(),
    )
    with pytest.raises(leave_engine.NotAuthorizedError):
        await leave_engine.decide_step(
            db_session,
            leave_request=request,
            stage_number=1,
            decision="Approved",
            note=None,
            actor=reference_data["vice_dean"],  # not the stage-1 assignee
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_submission_is_idempotent(db_session, reference_data):
    submission_id = _uid()
    first = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=submission_id,
        correlation_id=_uid(),
    )
    second = await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["ta"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["substitute"].id,
        reason="Family event",
        submission_id=submission_id,
        correlation_id=_uid(),
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_exceeding_max_consecutive_days_is_rejected(db_session, reference_data):
    # Casual leave caps at 2 consecutive working days.
    with pytest.raises(leave_engine.LeaveValidationError):
        await leave_engine.submit_leave_request(
            db_session,
            applicant=reference_data["hod"],  # not a TA, no substitute needed
            leave_type=reference_data["casual"],
            start_date=date(2026, 1, 4),  # Sun
            end_date=date(2026, 1, 6),  # Tue -> 3 working days
            substitute_id=None,
            reason="Too long for casual leave",
            submission_id=_uid(),
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_substitute_on_leave_in_same_period_is_rejected(db_session, reference_data):
    # First, substitute submits a leave request for Jan 4 - Jan 5
    await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["substitute"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=reference_data["ta"].id,
        reason="Substitute's own vacation",
        submission_id=_uid(),
        correlation_id=_uid(),
    )

    # TA attempts to select the substitute for an overlapping period (Jan 4 - Jan 5)
    with pytest.raises(leave_engine.LeaveValidationError, match="Selected substitute colleague has an active or pending leave request"):
        await leave_engine.submit_leave_request(
            db_session,
            applicant=reference_data["ta"],
            leave_type=reference_data["annual"],
            start_date=date(2026, 1, 4),
            end_date=date(2026, 1, 5),
            substitute_id=reference_data["substitute"].id,
            reason="TA's vacation",
            submission_id=_uid(),
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_applicant_on_leave_in_same_period_is_rejected(db_session, reference_data):
    # First leave request
    await leave_engine.submit_leave_request(
        db_session,
        applicant=reference_data["hod"],
        leave_type=reference_data["annual"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        substitute_id=None,
        reason="First request",
        submission_id=_uid(),
        correlation_id=_uid(),
    )

    # Second leave request by same applicant overlapping with first request
    with pytest.raises(leave_engine.LeaveValidationError, match="You already have an active or pending leave request"):
        await leave_engine.submit_leave_request(
            db_session,
            applicant=reference_data["hod"],
            leave_type=reference_data["casual"],
            start_date=date(2026, 1, 5),
            end_date=date(2026, 1, 6),
            substitute_id=None,
            reason="Overlapping request",
            submission_id=_uid(),
            correlation_id=_uid(),
        )

