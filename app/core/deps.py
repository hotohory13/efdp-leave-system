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
    result = await db.execute(select(Employee).where(Employee.email == payload["sub"]))
    employee = result.scalar_one_or_none()
    if not employee or not employee.is_active:
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
    result = await db.execute(select(Employee).where(Employee.email == payload["sub"]))
    return result.scalar_one_or_none()


def require_roles(*roles: EmployeeRole):
    async def dependency(employee: Employee = Depends(get_current_employee)) -> Employee:
        if employee.role not in roles and employee.role != EmployeeRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return employee

    return dependency


require_admin = require_roles(EmployeeRole.ADMIN)
require_manager = require_roles(EmployeeRole.HEAD_OF_DEPARTMENT, EmployeeRole.VICE_DEAN, EmployeeRole.ADMIN)
