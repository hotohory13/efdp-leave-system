from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.employee import Employee
from app.models.enums import EmployeeRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def _resolve_employee_from_payload(payload: dict, db: AsyncSession) -> Employee | None:
    email = payload.get("sub")
    if not email:
        return None
    result = await db.execute(select(Employee).where(Employee.email == email))
    employee = result.scalar_one_or_none()
    if employee is not None:
        return employee if employee.is_active else None

    # Serverless container recovery:
    # If container worker recycled and employee isn't in worker's /tmp/efdp.db,
    # trigger init_models() auto-seeder to restore standard demo accounts.
    from app.core.database import init_models
    await init_models()

    result = await db.execute(select(Employee).where(Employee.email == email))
    employee = result.scalar_one_or_none()
    if employee is not None:
        return employee if employee.is_active else None

    # Recreate custom account dynamically from verified signed JWT claims
    from app.models.enums import EmployeeRole, EmploymentStatus
    from app.models.org import Department

    dept_result = await db.execute(select(Department))
    dept = dept_result.scalars().first()
    if not dept:
        return None

    role_val = payload.get("role", "TeachingAssistant")
    try:
        role_enum = EmployeeRole(role_val)
    except ValueError:
        role_enum = EmployeeRole.TEACHING_ASSISTANT

    name_part = email.split("@")[0]
    employee = Employee(
        email=email,
        employee_code=name_part.upper(),
        full_name_en=name_part.replace(".", " ").title(),
        full_name_ar=name_part.replace(".", " ").title(),
        hashed_password="",
        department_id=dept.id,
        role=role_enum,
        employment_status=EmploymentStatus.ACTIVE,
    )
    db.add(employee)
    await db.commit()
    await db.refresh(employee)
    return employee


async def get_current_employee(
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    session_token: Annotated[str | None, Cookie(alias="efdp_token")] = None,
    db: AsyncSession = Depends(get_db),
) -> Employee:
    """Accepts either a Bearer token (API clients) or the `efdp_token`
    cookie (the server-rendered UI) so the same auth layer serves both."""
    raw_token = token or session_token
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")
    employee = await _resolve_employee_from_payload(payload, db)
    if not employee:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found or inactive")
    return employee


async def get_current_employee_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)] = None,
    session_token: Annotated[str | None, Cookie(alias="efdp_token")] = None,
    db: AsyncSession = Depends(get_db),
) -> Employee | None:
    raw_token = token or session_token
    if not raw_token:
        return None
    payload = decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        return None
    return await _resolve_employee_from_payload(payload, db)


def require_roles(*roles: EmployeeRole):
    async def dependency(employee: Employee = Depends(get_current_employee)) -> Employee:
        if employee.role not in roles and employee.role != EmployeeRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return employee

    return dependency


require_admin = require_roles(EmployeeRole.ADMIN)
require_manager = require_roles(EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN)
