from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misc import AuditLog


async def record(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_key: str,
    action: str,
    resolved_actor_id: int | None,
    claimed_actor_email: str | None = None,
    details: str | None = None,
    correlation_id: str | None = None,
) -> None:
    """Append-only by construction — nothing in this module updates or
    deletes a row (mirrors EFSOP_AuditLog, Part 3 §5.7)."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_key=entity_key,
        action=action,
        resolved_actor_id=resolved_actor_id,
        claimed_actor_email=claimed_actor_email,
        details=details,
        correlation_id=correlation_id,
    )
    db.add(entry)
