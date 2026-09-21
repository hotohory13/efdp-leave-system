"""
EFDP — application entrypoint.

Wires together the API routers, the server-rendered UI router, static
files, and the APScheduler background jobs (the Power Automate scheduled-
flow replacement). Run with:

    uvicorn app.main:app --reload

On startup in a fresh environment (no Alembic history yet) this also
creates tables directly via `init_models()` as a zero-config convenience —
see README for why this is safe (it is a no-op once Alembic is in use;
`Base.metadata.create_all` never touches a table that already exists) and
why production deployments should still run `alembic upgrade head`
explicitly rather than relying on it.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_models
from app.routers import (
    admin,
    attendance,
    auth,
    dashboard,
    employees,
    leave_requests,
    official_duties,
    reference_data,
    web,
)
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("efdp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("EFDP starting up (%s environment)", settings.ENVIRONMENT)
    await init_models()
    scheduler = start_scheduler()
    logger.info("Scheduler started: sla_sweep (hourly), nightly_metrics (01:00 UTC).")
    yield
    scheduler.shutdown(wait=False)
    logger.info("EFDP shutting down.")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- JSON API routers -------------------------------------------------------
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(reference_data.router)
app.include_router(leave_requests.router)
app.include_router(official_duties.router)
app.include_router(dashboard.router)
app.include_router(admin.router)

# --- Server-rendered UI (session-cookie based) ------------------------------
app.include_router(web.router)
app.include_router(attendance.router)


@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
