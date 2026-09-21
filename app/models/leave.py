from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ApprovalStepStatus, EmployeeRole, LeaveRequestStatus


class LeaveType(Base):
    """EFSOP_LeaveTypes — the permitted leave types and their rules.
    Business keys اعتيادي (annual) and عارضة (casual) are preserved verbatim
    per the source design's own naming convention (§1, Part 3)."""

    __tablename__ = "leave_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # عارضة / اعتيادي
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    annual_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    max_consecutive_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # See docs/BUSINESS_RULES.md and Settings.CASUAL_LEAVE_DEDUCTS_FROM_ANNUAL —
    # this per-type flag is the authoritative value once HR confirms OD-03;
    # the global setting is only the seed-time default.
    deducts_from_annual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LeaveBalance(Base):
    """EFSOP_LeaveBalances — one row per person, per year, per leave type.
    Reservation model (ADR-07): PendingDays reserved at submission, converted
    to UsedDays only at final approval. `entitled - used - pending >= 0` is
    enforced at the service layer on every write (mirrors the SharePoint
    list validation formula's overdraft constraint)."""

    __tablename__ = "leave_balances"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "year", name="uq_balance_person_type_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)

    entitled_days: Mapped[float] = mapped_column(Integer, nullable=False, default=0)
    used_days: Mapped[float] = mapped_column(Integer, nullable=False, default=0)
    pending_days: Mapped[float] = mapped_column(Integer, nullable=False, default=0)

    employee: Mapped["Employee"] = relationship()
    leave_type: Mapped["LeaveType"] = relationship()

    @property
    def remaining_days(self) -> float:
        return self.entitled_days - self.used_days - self.pending_days


class LeaveRequest(Base):
    """EFSOP_LeaveRequests — the system of record for every leave request.
    One row per request, never deleted, status-driven (Part 3 §5.1)."""

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_key: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)  # LR-2026-00042
    submission_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # idempotency

    applicant_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    # Denormalised, load-bearing snapshot (Part 3 §5.1): written by the
    # service from the Directory at submission time, never accepted from the
    # client — it is what makes the substitute rule (BR-03) enforceable.
    applicant_role: Mapped[EmployeeRole] = mapped_column(Enum(EmployeeRole), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)

    leave_type_id: Mapped[int] = mapped_column(ForeignKey("leave_types.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    request_year: Mapped[int] = mapped_column(Integer, nullable=False)
    working_days: Mapped[int] = mapped_column(Integer, nullable=False)

    substitute_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    substitute_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    substitute_objection: Mapped[str | None] = mapped_column(Text, nullable=True)  # OD-11: notify, not block

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[LeaveRequestStatus] = mapped_column(
        Enum(LeaveRequestStatus), default=LeaveRequestStatus.PENDING_STAGE_1, nullable=False, index=True
    )
    current_stage: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    applicant: Mapped["Employee"] = relationship(foreign_keys=[applicant_id])
    substitute: Mapped["Employee | None"] = relationship(foreign_keys=[substitute_id])
    department: Mapped["Department"] = relationship()
    leave_type: Mapped["LeaveType"] = relationship()
    approval_steps: Mapped[list["ApprovalStep"]] = relationship(
        back_populates="request", order_by="ApprovalStep.stage_number", cascade="all, delete-orphan"
    )


class ApprovalStep(Base):
    """EFSOP_ApprovalSteps — the two-stage state machine (OD-02, as resolved
    in Part 3 §5.3): stage 1 Head of Department, stage 2 Vice Dean. Two rows
    per request. `last_reminder_at` is the watermark that prevents reminder
    spam from the hourly SLA sweep (mirrors FL-08 / US-12)."""

    __tablename__ = "approval_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("leave_requests.id"), nullable=False)
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 or 2
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)  # HeadOfDepartment / ViceDean

    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    delegated_from_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    status: Mapped[ApprovalStepStatus] = mapped_column(
        Enum(ApprovalStepStatus), default=ApprovalStepStatus.PENDING, nullable=False, index=True
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped["LeaveRequest"] = relationship(back_populates="approval_steps")
    assigned_to: Mapped["Employee | None"] = relationship(foreign_keys=[assigned_to_id])
    delegated_from: Mapped["Employee | None"] = relationship(foreign_keys=[delegated_from_id])


class ApprovalRoute(Base):
    """EFSOP_ApprovalRoutes — which role approves at which stage, with
    per-stage SLA. This is what makes the approval chain configuration
    (FR-LV-17) rather than a redeploy: adding a stage is rows here, not code."""

    __tablename__ = "approval_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    stage_name: Mapped[str] = mapped_column(String(32), nullable=False)
    role_required: Mapped[EmployeeRole] = mapped_column(Enum(EmployeeRole), nullable=False)
    sla_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    escalation_hours: Mapped[int] = mapped_column(Integer, nullable=False)


class ApprovalDelegation(Base):
    """EFSOP_ApprovalDelegations (AR-07) — temporary transfer of approval
    authority so a single absent approver cannot stall every request behind
    them. Designed per Part 3 §2.2; deploy or leave unused per the sponsor's
    choice — nothing else in the approval engine depends on rows existing here."""

    __tablename__ = "approval_delegations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    to_employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    from_employee: Mapped["Employee"] = relationship(foreign_keys=[from_employee_id])
    to_employee: Mapped["Employee"] = relationship(foreign_keys=[to_employee_id])
