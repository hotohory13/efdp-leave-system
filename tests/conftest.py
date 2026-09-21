"""
Test fixtures.

Uses a throwaway on-disk SQLite database (not `:memory:` — the async
engine's default pool would hand different connections a different
in-memory database, which looks like tables silently vanishing) created
fresh for the whole test session and removed afterwards. The DATABASE_URL
env var must be set before `app.core.config` is ever imported, so this
file sets it at module load time, ahead of any other test file's imports.
"""
import os
import uuid
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parent / f"test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key"

import pytest_asyncio  # noqa: E402

from app.core.database import Base, engine  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.models.enums import EmployeeRole  # noqa: E402
from app.models.leave import ApprovalRoute, LeaveType  # noqa: E402
from app.models.org import Department  # noqa: E402


@pytest_asyncio.fixture()
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def reference_data(db_session):
    """A department with one Head of Department + one Vice Dean, the two
    seed leave types, and the two-stage approval route — the minimum
    fixture every leave/duty engine test needs."""
    department = Department(code="EEC", name_en="Electrical Engineering", name_ar="الهندسة الكهربية")
    db_session.add(department)
    await db_session.flush()

    annual = LeaveType(code="اعتيادي", name_en="Annual Leave", name_ar="إجازة اعتيادية", annual_cap=21, max_consecutive_days=15, deducts_from_annual=False)
    casual = LeaveType(code="عارضة", name_en="Casual Leave", name_ar="إجازة عارضة", annual_cap=6, max_consecutive_days=2, deducts_from_annual=False)
    db_session.add_all([annual, casual])

    db_session.add_all(
        [
            ApprovalRoute(stage_number=1, stage_name="HeadOfDepartment", role_required=EmployeeRole.HEAD_OF_DEPARTMENT, sla_hours=24, escalation_hours=48),
            ApprovalRoute(stage_number=2, stage_name="ViceDean", role_required=EmployeeRole.VICE_DEAN, sla_hours=24, escalation_hours=48),
        ]
    )

    hod = Employee(
        employee_code="EEC-0002", full_name_en="Head of EEC", full_name_ar="رئيس القسم", email="hod.eec@acu.edu.eg",
        hashed_password=hash_password("x"), department_id=department.id, role=EmployeeRole.HEAD_OF_DEPARTMENT,
    )
    vice_dean = Employee(
        employee_code="EEC-0001", full_name_en="Vice Dean", full_name_ar="وكيل الكلية", email="vicedean@acu.edu.eg",
        hashed_password=hash_password("x"), department_id=department.id, role=EmployeeRole.VICE_DEAN,
    )
    ta = Employee(
        employee_code="EEC-0143", full_name_en="Sara TA", full_name_ar="سارة", email="sara@acu.edu.eg",
        hashed_password=hash_password("x"), department_id=department.id, role=EmployeeRole.TEACHING_ASSISTANT,
    )
    substitute = Employee(
        employee_code="EEC-0144", full_name_en="Substitute TA", full_name_ar="بديل", email="sub@acu.edu.eg",
        hashed_password=hash_password("x"), department_id=department.id, role=EmployeeRole.TEACHING_ASSISTANT,
    )
    db_session.add_all([hod, vice_dean, ta, substitute])
    await db_session.commit()

    return {
        "department": department,
        "annual": annual,
        "casual": casual,
        "hod": hod,
        "vice_dean": vice_dean,
        "ta": ta,
        "substitute": substitute,
    }


def pytest_sessionfinish(session, exitstatus):
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink(missing_ok=True)
        except OSError:
            pass

