import pytest

from app.services import balance_engine


@pytest.mark.asyncio
async def test_get_or_create_balance_initialises_from_leave_type_cap(db_session, reference_data):
    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    assert balance.entitled_days == 21
    assert balance.used_days == 0
    assert balance.pending_days == 0
    assert balance.remaining_days == 21


@pytest.mark.asyncio
async def test_reserve_then_commit(db_session, reference_data):
    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    balance_engine.reserve(balance, 5)
    assert balance.pending_days == 5
    assert balance.remaining_days == 16

    balance_engine.commit_pending_to_used(balance, 5)
    assert balance.pending_days == 0
    assert balance.used_days == 5
    assert balance.remaining_days == 16


@pytest.mark.asyncio
async def test_reserve_then_release(db_session, reference_data):
    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    balance_engine.reserve(balance, 5)
    balance_engine.release_pending(balance, 5)
    assert balance.pending_days == 0
    assert balance.used_days == 0
    assert balance.remaining_days == 21


@pytest.mark.asyncio
async def test_reserve_beyond_entitlement_raises(db_session, reference_data):
    balance = await balance_engine.get_or_create_balance(
        db_session, employee=reference_data["ta"], leave_type=reference_data["annual"], year=2026
    )
    with pytest.raises(balance_engine.InsufficientBalanceError):
        balance_engine.reserve(balance, 22)
