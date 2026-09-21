from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_employee
from app.models.employee import Employee
from app.services import dashboard_service

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/balances/mine")
async def my_balances(
    year: int | None = None, db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)
):
    return await dashboard_service.get_my_balances(db, employee, year)


@router.get("/dashboard/summary")
async def dashboard_summary(db: AsyncSession = Depends(get_db), employee: Employee = Depends(get_current_employee)):
    return await dashboard_service.get_dashboard_summary(db, employee)
