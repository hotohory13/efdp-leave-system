# EFDP — Employee & Leave Management System

A Python port of the original Power Platform EFDP system (Power Apps
Canvas + Power Automate + SharePoint/Dataverse) for the Faculty of
Engineering, Ahram Canadian University. FastAPI + SQLAlchemy 2.0 (async)
+ APScheduler, server-rendered UI (Jinja2 + Bootstrap 5) plus a JSON API.

See `PROGRESS.md` for the build history and `docs/BUSINESS_RULES.md` for
every business-rule assumption made against an open decision (`OD-xx`) in
the source EFSOP documents — **read that before any real deployment.**

## Quick start (zero-config, SQLite)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # defaults already work as-is

# Reference data only (departments, leave types, holidays, settings):
python -m scripts.seed_data

# OR, for a local demo you can actually log into (sample staff +
# a break-glass admin account — see the warning below):
python -m scripts.seed_data --demo

uvicorn app.main:app --reload
```

Visit `http://localhost:8000`. Tables are created automatically on first
run (`init_models()` in `app/main.py`'s lifespan) so the app is usable
immediately; production deployments should switch to Alembic (see below).

### Demo logins (only if you ran `--demo`)

| Role | Email | Password |
|---|---|---|
| Admin | `admin@efdp.local` | `Admin@12345` |
| Vice Dean | `bassem.sheta@acu.edu.eg` | `Passw0rd!` |
| Head of Department (EEC) | `hod.eec@acu.edu.eg` | `Passw0rd!` |
| Teaching Assistant | `s.abdelgawad@acu.edu.eg` | `Passw0rd!` |

**`--demo` is for local/dev use only.** The real `Employees` sheet in
`scripts/EFDP-Employees.xlsx` is deliberately empty (see
`docs/BUSINESS_RULES.md`) — never run `--demo` against a database that
also holds real staff data.

## Running with Docker

```bash
docker compose up --build
```

This builds the app image, starts Postgres, runs `alembic upgrade head`
on container start, and serves on `http://localhost:8000`. Seed it once
the containers are up:

```bash
docker compose exec app python -m scripts.seed_data --demo
```

## Database migrations (Alembic)

The zero-config `init_models()` path (SQLite dev) and Alembic are both
valid; pick one per environment and don't mix them against the same
database.

```bash
alembic upgrade head                 # apply migrations
alembic revision --autogenerate -m "description"   # after a model change
```

`alembic/env.py` reads `DATABASE_URL` from `app.core.config.settings`
(i.e. from `.env`), so there is exactly one place the connection string
is configured.

## Running the tests

```bash
pytest
```

Tests use a throwaway on-disk SQLite database created fresh per session
(see `tests/conftest.py`) — no external services required. Covers the
working-day calculator, the balance reservation engine (overdraft
protection), the full two-stage leave approval state machine (submit →
Head of Department → Vice Dean, rejection, idempotency, authorization),
and the official-duty engine.

## Project layout

```
app/
  core/         settings, async DB session factory, JWT auth, role guards
  models/       SQLAlchemy 2.0 ORM models (Employee, Leave*, OfficialDuty, ...)
  schemas/      Pydantic v2 request/response schemas
  services/     business logic — leave_engine, balance_engine, duty_engine,
                calendar_engine, notifications, audit, scheduler
  routers/      JSON API endpoints (/api/...)
  routers/web.py  server-rendered UI pages (session-cookie auth)
  templates/    Jinja2 templates (Bootstrap 5)
  static/       CSS, faculty logo
scripts/
  seed_data.py  parses the original .xlsx workbooks into the database
  EFDP-*.xlsx   the source EFSOP seed workbooks, copied in unmodified
alembic/        migrations
docs/
  BUSINESS_RULES.md   traceability table — every OD-xx assumption
tests/
```

## Key business rules (see `docs/BUSINESS_RULES.md` for the full table)

- No daily attendance register (OD-01) — Official Duties (مأمورية) is the
  entire attendance module.
- Two-stage approval: Head of Department → Vice Dean (OD-02), held as
  configuration (`approval_routes` table), not hardcoded.
- Whether عارضة (Casual Leave) deducts from the اعتيادي (Annual) balance
  was left **Unconfirmed** in the source workbook (OD-03) — defaults to
  **No**. **Confirm against لائحة شؤون العاملين before production.**
- Entitlement figures (21 annual / 6 casual days) are placeholders from
  the source seed data, explicitly flagged as **not for production**
  until HR confirms real figures.
- Holiday calendar only has fixed-date national holidays for 2026 —
  movable religious holidays must be added once announced (OD-04).

## Known limitations

- `next_request_key`/`next_duty_key` (`app/services/keys.py`) are not
  perfectly race-safe under SQLite without a serializing transaction —
  acceptable at pilot scale; wrap in `SERIALIZABLE` isolation on
  PostgreSQL if concurrent submission volume grows.
- SMTP is optional; with no `SMTP_HOST` configured, notifications are
  logged to `notification_log` as `SkippedNoSmtp` rather than sent —
  visible in Admin → Notification Log.

---

**Faculty of Engineering, Ahram Canadian University**
Developer: ENG. Omar Yasser
