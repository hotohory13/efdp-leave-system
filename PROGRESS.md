# EFDP — Work in progress, saved state

Generation was stopped deliberately at this point. Nothing below is
incomplete-but-broken — every file listed here is finished and internally
consistent; the project is just not yet wired into a runnable app (no
main.py, no seed script, no migrations, no remaining UI pages).

## What's done

**Data model** (`app/models/`) — Department, Program, Employee (Directory),
LeaveType, LeaveBalance, LeaveRequest, ApprovalStep, ApprovalRoute,
ApprovalDelegation, OfficialDuty, HolidayCalendar, AppSetting, AuditLog,
NotificationLog. SQLAlchemy 2.0 async style throughout.

**Core** (`app/core/`) — settings (every business-rule default documents
which open decision (OD-xx) from the source EFSOP docs it resolves),
async DB session factory, JWT + password hashing, auth dependencies /
role guards.

**Services** (`app/services/`) — working-day calculator, leave balance
reservation engine (pending → used, overdraft-protected), the full leave
submission/approval/rejection/cancellation state machine (two-stage:
Head of Department → Vice Dean, per Part 3's resolution of OD-02),
official-duty (مأمورية) engine, notification dispatch (SMTP optional,
always logged), audit logging, APScheduler SLA sweep.

**API routers** (`app/routers/`) — auth, employees, departments/leave-types
/holidays, leave-requests (submit/decide/cancel/queues), official-duties,
dashboard/balances, admin (settings/audit/notification log). Not yet
mounted into an app instance.

**UI** (`app/templates/`, `app/static/`) — base layout with faculty logo
and required footer ("Faculty of Engineering, Ahram Canadian University" /
"Developer: ENG. Omar Yasser"), login page, dashboard, new-leave-request
form, my-requests list. Custom CSS in `app/static/css/efdp.css`.

**Config** — `requirements.txt`, `.env.example` (documents every business
default and which source-document decision it stands in for).

## Not started yet

- `app/routers/web.py` — the server-side view functions that actually
  render the templates above via the session cookie (templates exist,
  nothing serves them yet)
- Approval queue UI, official-duties UI, admin panel UI
- `main.py` — FastAPI app assembly, router mounting, scheduler lifespan
- `scripts/seed_data.py` — parse the original `.xlsx` files (copied into
  `scripts/`) into the database
- Alembic migration setup (`alembic/` directory exists but is empty)
- `Dockerfile`, `docker-compose.yml`
- `docs/BUSINESS_RULES.md` — traceability table for every assumption made
  against an open decision in the source EFSOP documents
- `tests/`

## Key assumptions made so far (carry these forward)

The source documents (Part 1–3) contain explicit, self-flagged open
decisions. Where a later document resolved an earlier one, I followed the
later one; where nothing resolved it, I picked the documents' own stated
recommendation and marked it as a config default, not a hardcoded rule:

- No daily attendance check-in/out (OD-01) — official duties (مأمورية) is
  the whole attendance module, advance or retroactive with justification
  (OD-13, option 2).
- Two-stage approval, Head of Department → Vice Dean (OD-02, as resolved
  in Part 3 §5.3) — held in `ApprovalRoute` as configuration, not code.
- عارضة (casual leave) does **not** deduct from the annual balance by
  default (`CASUAL_LEAVE_DEDUCTS_FROM_ANNUAL=false`) — the source workbook
  left this "Unconfirmed"; confirm against لائحة شؤون العاملين before
  production use (OD-03).
- Entitlements (21 / 6 days) are the placeholder values from the source
  seed data — explicitly flagged in the original docs as **not for
  production** until HR confirms real figures (OD-03).
- Weekend = Friday/Saturday (`WEEKEND_DAYS=4,5`), configurable.
- Holiday calendar seed will be incomplete (movable religious holidays are
  announced by decree) — same caveat as the original design (OD-04).
