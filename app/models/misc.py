from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import NotificationChannel, NotificationStatus, OfficialDutyStatus


class OfficialDuty(Base):
    """EFSOP_OfficialDuties — مأمورية. Per OD-01 (no daily attendance
    register in the MVP) this list *is* the attendance module: advance
    registration, or retroactive registration with justification (OD-13,
    option 2). Consumes no leave entitlement."""

    __tablename__ = "official_duties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    duty_key: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)  # OD-2026-00012
    owner_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    duty_year: Mapped[int] = mapped_column(Integer, nullable=False)
    working_days: Mapped[int] = mapped_column(Integer, nullable=False)

    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_retroactive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    retro_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[OfficialDutyStatus] = mapped_column(
        Enum(OfficialDutyStatus), default=OfficialDutyStatus.PENDING, nullable=False, index=True
    )
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["Employee"] = relationship(foreign_keys=[owner_id])
    department: Mapped["Department"] = relationship()
    approved_by: Mapped["Employee | None"] = relationship(foreign_keys=[approved_by_id])


class HolidayCalendar(Base):
    """EFSOP_HolidayCalendar — official holidays for working-day
    computation. Blocked on OD-04 in the source design: incomplete without
    HR/Registrar confirmation, and movable religious holidays must be added
    by decree each year (see the ToAdd sheet in the original workbook)."""

    __tablename__ = "holidays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)


class AppSetting(Base):
    """EFSOP_Settings — key/value configuration, typed at the application
    layer. Seeded from EFDP-Settings.xlsx."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AuditLog(Base):
    """EFSOP_AuditLog — append-only record of every state transition.
    Records both the claimed and resolved actor identity (ADR-11 parallel):
    cheap now, and lets any divergence between the two be detected later."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    claimed_actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    resolved_actor: Mapped["Employee | None"] = relationship()


class NotificationLog(Base):
    """EFSOP_NotificationLog — recipient, channel, template, dispatch
    outcome. Supports NFR-12's fairness position: "the system did not hear
    from this person" is only defensible if dispatch is actually recorded."""

    __tablename__ = "notification_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
