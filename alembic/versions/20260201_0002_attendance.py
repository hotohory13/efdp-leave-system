"""attendance

Revision ID: 0002_attendance
Revises: 0001_initial_schema
Create Date: 2026-02-01 00:00:00

Adds the daily check-in/check-out register (app/models/attendance.py).
Hand-written to mirror the ORM model, same as 0001_initial_schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_attendance"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATTENDANCE_STATUS = sa.Enum("Present", "Incomplete", "Absent", name="attendancestatus")


def upgrade() -> None:
    op.create_table(
        "attendance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("check_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_hours", sa.Float(), nullable=True),
        sa.Column("status", ATTENDANCE_STATUS, nullable=False, server_default="Incomplete"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "date", name="uq_attendance_employee_date"),
    )
    op.create_index("ix_attendance_employee_id", "attendance", ["employee_id"])
    op.create_index("ix_attendance_date", "attendance", ["date"])
    op.create_index("ix_attendance_status", "attendance", ["status"])


def downgrade() -> None:
    op.drop_table("attendance")
