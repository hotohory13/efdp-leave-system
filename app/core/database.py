import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

db_url = settings.DATABASE_URL
if (os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV")) and "sqlite" in db_url and "./efdp.db" in db_url:
    db_url = "sqlite+aiosqlite:////tmp/efdp.db"

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args=connect_args,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_models():
    """Dev/Serverless convenience: create tables directly and seed demo data if database is empty."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        from app.models.org import Department
        result = await db.execute(select(Department))
        if result.first() is None:
            from scripts.seed_data import (
                seed_approval_routes,
                seed_custom_accounts,
                seed_demo_admin,
                seed_departments,
                seed_employees,
                seed_holidays,
                seed_leave_types,
                seed_settings,
            )
            await seed_departments(db)
            await seed_leave_types(db)
            await seed_holidays(db)
            await seed_settings(db)
            await seed_approval_routes(db)
            await seed_employees(db, sheet_name="Example", default_password="Passw0rd!")
            await seed_demo_admin(db)
            await seed_custom_accounts(db)
            await db.commit()


