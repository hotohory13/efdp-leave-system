from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee
from app.core.security import create_access_token, verify_password
from app.models.employee import Employee
from app.schemas.schemas import EmployeeOut, LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Employee).where(Employee.email == payload.email.lower()))
    employee = result.scalar_one_or_none()
    if not employee or not verify_password(payload.password, employee.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account is inactive")

    token = create_access_token(subject=employee.email, extra_claims={"role": employee.role.value})
    response.set_cookie(
        "efdp_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 8
    )
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("efdp_token")
    return {"detail": "Logged out"}


@router.get("/me", response_model=EmployeeOut)
async def me(employee: Employee = Depends(get_current_employee)):
    return employee
