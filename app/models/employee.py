from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import EmployeeRole, EmploymentStatus


class Employee(Base):
    """The Directory — every TA and staff member. The business-role source
    of record (EFSOP_Directory, Part 3 §5.5). Deactivation is a status
    change, never a deletion (FR-DIR-05) — a deleted row would orphan every
    historical request that names this person."""

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)  # EEC-0001
    full_name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name_ar: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    program_id: Mapped[int | None] = mapped_column(ForeignKey("programs.id"), nullable=True)
    academic_rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[EmployeeRole] = mapped_column(Enum(EmployeeRole), nullable=False)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(EmploymentStatus), default=EmploymentStatus.ACTIVE, nullable=False
    )
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    department: Mapped["Department"] = relationship(
        back_populates="employees", foreign_keys=[department_id]
    )
    program: Mapped["Program | None"] = relationship()
    supervisor: Mapped["Employee | None"] = relationship(remote_side=[id])

    @property
    def is_active(self) -> bool:
        return self.employment_status == EmploymentStatus.ACTIVE
