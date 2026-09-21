"""
Background jobs — the Power Automate scheduled-flow replacement (FL-08 /
SCHEDULED-FLOWS.md), adapted to the MVP scope actually resolved in Parts
1-3 (no daily attendance register — OD-01 removed it; official duties and
leave are what remain).

Two jobs, run by APScheduler in-process:

  * `sla_sweep` — hourly. Sends exactly one reminder to an approver whose
    step has passed its SLA and has not yet been reminded (the
    `last_reminder_at` watermark is what stops reminder spam, per US-12).
  * `nightly_metrics` — once daily. Recomputes the dashboard's aggregate
    counters so dashboard screens read a small precomputed table rather
    than aggregating the live requests table on every page view (ADR-19).
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.employee import Employee
from app.models.enums import ApprovalStepStatus
from app.models.leave import ApprovalStep
from app.models.misc import AppSetting
from app.services import notifications

logger = logging.getLogger("efdp.scheduler")


async def sla_sweep() -> None:
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(ApprovalStep).where(
                ApprovalStep.status == ApprovalStepStatus.PENDING,
                ApprovalStep.sla_due_at <= now,
                ApprovalStep.last_reminder_at.is_(None),
            )
        )
        overdue_steps = result.scalars().all()
        for step in overdue_steps:
            if not step.assigned_to_id:
                continue
            approver = await db.get(Employee, step.assigned_to_id)
            if not approver:
                continue
            await notifications.send(
                db,
                recipient_email=approver.email,
                subject="Reminder: a leave request is awaiting your decision",
                body=(
                    f"Approval step (stage {step.stage_number}) for request "
                    f"#{step.request_id} passed its SLA and is still pending your decision."
                ),
                template_key="sla_reminder",
            )
            step.last_reminder_at = now
        if overdue_steps:
            logger.info("SLA sweep: sent %d reminder(s)", len(overdue_steps))
        await db.commit()


async def nightly_metrics() -> None:
    """Precomputes a handful of dashboard counters into app_settings under a
    `metric:` prefix — deliberately simple (a few key/value rows, not a
    metrics table) since the MVP scope has nowhere near SharePoint's
    5,000-row query ceiling that motivated the original design's separate
    metrics list (ADR-19)."""
    from app.models.enums import LeaveRequestStatus, OfficialDutyStatus
    from app.models.leave import LeaveRequest
    from app.models.misc import OfficialDuty

    async with AsyncSessionLocal() as db:
        pending = await db.execute(
            select(LeaveRequest).where(
                LeaveRequest.status.in_(
                    [LeaveRequestStatus.PENDING_STAGE_1, LeaveRequestStatus.PENDING_STAGE_2]
                )
            )
        )
        pending_count = len(pending.scalars().all())

        approved = await db.execute(select(LeaveRequest).where(LeaveRequest.status == LeaveRequestStatus.APPROVED))
        approved_count = len(approved.scalars().all())

        duties_pending = await db.execute(select(OfficialDuty).where(OfficialDuty.status == OfficialDutyStatus.PENDING))
        duties_pending_count = len(duties_pending.scalars().all())

        for key, value in (
            ("metric:pending_leave_requests", str(pending_count)),
            ("metric:approved_leave_requests", str(approved_count)),
            ("metric:pending_official_duties", str(duties_pending_count)),
            ("metric:last_computed_utc", datetime.now(timezone.utc).isoformat()),
        ):
            existing = await db.execute(select(AppSetting).where(AppSetting.key == key))
            row = existing.scalar_one_or_none()
            if row:
                row.value = value
            else:
                db.add(AppSetting(key=key, value=value, description="Precomputed nightly metric."))
        await db.commit()
        logger.info("Nightly metrics recomputed.")


def start_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(sla_sweep, "interval", hours=1, id="sla_sweep", next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(nightly_metrics, "cron", hour=1, minute=0, id="nightly_metrics")
    scheduler.start()
    return scheduler
