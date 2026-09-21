from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.employee import Employee
from app.models.misc import AppSetting, AuditLog, NotificationLog
from app.schemas.schemas import AppSettingOut, AppSettingUpdate

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/settings", response_model=list[AppSettingOut])
async def list_settings(db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)):
    result = await db.execute(select(AppSetting).where(~AppSetting.key.like("metric:%")).order_by(AppSetting.key))
    return result.scalars().all()


@router.patch("/settings/{key}", response_model=AppSettingOut)
async def update_setting(
    key: str, payload: AppSettingUpdate, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    setting.value = payload.value
    await db.commit()
    await db.refresh(setting)
    return setting


@router.get("/audit-log")
async def list_audit_log(limit: int = 200, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)):
    result = await db.execute(select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(limit))
    return [
        {
            "entity_type": a.entity_type,
            "entity_key": a.entity_key,
            "action": a.action,
            "resolved_actor_id": a.resolved_actor_id,
            "details": a.details,
            "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
        }
        for a in result.scalars().all()
    ]


@router.get("/notification-log")
async def list_notification_log(
    limit: int = 200, db: AsyncSession = Depends(get_db), _: Employee = Depends(require_admin)
):
    result = await db.execute(select(NotificationLog).order_by(NotificationLog.occurred_at.desc()).limit(limit))
    return [
        {
            "recipient_email": n.recipient_email,
            "subject": n.subject,
            "status": n.status.value,
            "template_key": n.template_key,
            "occurred_at": n.occurred_at.isoformat() if n.occurred_at else None,
        }
        for n in result.scalars().all()
    ]
