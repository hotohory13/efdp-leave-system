import uuid
from datetime import date

import pytest

from app.models.enums import OfficialDutyStatus
from app.services import duty_engine


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_submit_and_approve_duty(db_session, reference_data):
    duty = await duty_engine.submit_duty(
        db_session,
        owner=reference_data["ta"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        destination="Ministry of Education",
        purpose="Accreditation meeting",
        is_retroactive=False,
        retro_justification=None,
        evidence_url=None,
        correlation_id=_uid(),
    )
    assert duty.status == OfficialDutyStatus.PENDING
    assert duty.working_days == 2

    updated = await duty_engine.decide_duty(
        db_session, duty=duty, decision="Approved", note=None, actor=reference_data["hod"], correlation_id=_uid()
    )
    assert updated.status == OfficialDutyStatus.APPROVED
    assert updated.approved_by_id == reference_data["hod"].id


@pytest.mark.asyncio
async def test_retroactive_duty_requires_justification(db_session, reference_data):
    with pytest.raises(duty_engine.DutyValidationError):
        await duty_engine.submit_duty(
            db_session,
            owner=reference_data["ta"],
            start_date=date(2026, 1, 4),
            end_date=date(2026, 1, 4),
            destination="Conference",
            purpose="Late filing",
            is_retroactive=True,
            retro_justification="too short",
            evidence_url=None,
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_non_manager_cannot_decide_duty(db_session, reference_data):
    duty = await duty_engine.submit_duty(
        db_session,
        owner=reference_data["ta"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 4),
        destination="Site visit",
        purpose="Lab inspection",
        is_retroactive=False,
        retro_justification=None,
        evidence_url=None,
        correlation_id=_uid(),
    )
    with pytest.raises(duty_engine.NotAuthorizedError):
        await duty_engine.decide_duty(
            db_session,
            duty=duty,
            decision="Approved",
            note=None,
            actor=reference_data["substitute"],  # a fellow TA, not a manager
            correlation_id=_uid(),
        )


@pytest.mark.asyncio
async def test_official_duty_does_not_deduct_from_leave_balance(db_session, reference_data):
    from app.services import balance_engine

    # Check initial leave balance
    balance_before = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    initial_used = balance_before.used_days
    initial_pending = balance_before.pending_days

    # Submit and approve an official duty
    duty = await duty_engine.submit_duty(
        db_session,
        owner=reference_data["ta"],
        start_date=date(2026, 1, 4),
        end_date=date(2026, 1, 5),
        destination="External Committee",
        purpose="Official university delegation",
        is_retroactive=False,
        retro_justification=None,
        evidence_url=None,
        correlation_id=_uid(),
    )
    await duty_engine.decide_duty(
        db_session, duty=duty, decision="Approved", note=None, actor=reference_data["hod"], correlation_id=_uid()
    )

    # Verify leave balance remains completely untouched
    balance_after = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    assert balance_after.used_days == initial_used
    assert balance_after.pending_days == initial_pending
