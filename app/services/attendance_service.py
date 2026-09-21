"""
Attendance engine.

A daily clock-in/clock-out register, one row per employee per calendar
day (see app/models/attendance.py). This sits alongside — and does not
replace — the OfficialDuty-based away-from-campus log (OD-01); that log
still covers مأمورية travel, this one covers on-campus daily presence.

Also builds the branded "Faculty of Engineering - Attendance Report" PDF,
following the same reportlab/Platypus conventions as
app/services/report_pdf.py so both reports share a visual language.
"""
import io
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timezone import now_utc, to_local, today_local
from app.models.attendance import Attendance
from app.models.employee import Employee
from app.models.enums import AttendanceStatus
from app.models.org import Department
from app.services import audit

NAVY = colors.HexColor("#1b2a4a")
LIGHT_GREY = colors.HexColor("#f2f3f5")
MID_GREY = colors.HexColor("#6b7280")
BORDER = colors.HexColor("#d7dae0")

PAGE_SIZE = landscape(A4)
MARGIN = 1.4 * cm
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN


class AttendanceValidationError(Exception):
    pass


# --- Employee-facing actions -------------------------------------------------
async def get_today_attendance(db: AsyncSession, employee: Employee, day: date | None = None) -> Attendance | None:
    target_day = day or today_local()
    result = await db.execute(
        select(Attendance).where(Attendance.employee_id == employee.id, Attendance.date == target_day)
    )
    return result.scalar_one_or_none()


async def check_in(db: AsyncSession, *, employee: Employee, correlation_id: str | None = None) -> Attendance:
    today = today_local()
    now = now_utc()
    record = await get_today_attendance(db, employee, today)

    if record and record.check_in is not None:
        raise AttendanceValidationError("You have already checked in today.")

    if record is None:
        record = Attendance(employee_id=employee.id, date=today, check_in=now, status=AttendanceStatus.INCOMPLETE)
        db.add(record)
    else:
        record.check_in = now
        record.status = AttendanceStatus.INCOMPLETE

    await db.flush()
    await audit.record(
        db,
        entity_type="Attendance",
        entity_key=f"{employee.employee_code}-{today.isoformat()}",
        action="CheckIn",
        resolved_actor_id=employee.id,
        details=f"{employee.full_name_en} checked in at {to_local(now).strftime('%Y-%m-%d %H:%M %Z')}.",
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def check_out(db: AsyncSession, *, employee: Employee, correlation_id: str | None = None) -> Attendance:
    today = today_local()
    now = now_utc()
    record = await get_today_attendance(db, employee, today)

    if record is None or record.check_in is None:
        raise AttendanceValidationError("You must check in before you can check out.")
    if record.check_out is not None:
        raise AttendanceValidationError("You have already checked out today.")

    check_in_time = record.check_in
    if check_in_time.tzinfo is None:
        check_in_time = check_in_time.replace(tzinfo=timezone.utc)

    record.check_out = now
    record.total_hours = round((now - check_in_time).total_seconds() / 3600, 2)
    record.status = AttendanceStatus.PRESENT

    await db.flush()
    await audit.record(
        db,
        entity_type="Attendance",
        entity_key=f"{employee.employee_code}-{today.isoformat()}",
        action="CheckOut",
        resolved_actor_id=employee.id,
        details=(
            f"{employee.full_name_en} checked out at {to_local(now).strftime('%Y-%m-%d %H:%M %Z')} "
            f"({record.total_hours} hours logged)."
        ),
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(record)
    return record


async def get_my_attendance(
    db: AsyncSession, employee: Employee, year: int | None = None, month: int | None = None
) -> list[Attendance]:
    """Monthly (or full-year, if month is None) attendance history for one employee, most recent first."""
    target_year = year or today_local().year
    query = select(Attendance).where(Attendance.employee_id == employee.id)
    if target_year:
        query = query.where(
            Attendance.date >= date(target_year, 1, 1),
            Attendance.date < date(target_year + 1, 1, 1),
        )
    if month:
        start = date(target_year, month, 1)
        end = date(target_year + 1, 1, 1) if month == 12 else date(target_year, month + 1, 1)
        query = query.where(Attendance.date >= start, Attendance.date < end)
    result = await db.execute(query.order_by(Attendance.date.desc()))
    return list(result.scalars().all())


# --- Admin overview & filtering ----------------------------------------------
async def get_filtered_attendance(
    db: AsyncSession,
    *,
    department_id: int | None = None,
    employee_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[tuple[Attendance, Employee, Department]]:
    query = (
        select(Attendance, Employee, Department)
        .join(Employee, Employee.id == Attendance.employee_id)
        .join(Department, Department.id == Employee.department_id)
    )
    if department_id:
        query = query.where(Employee.department_id == department_id)
    if employee_id:
        query = query.where(Attendance.employee_id == employee_id)
    if start_date:
        query = query.where(Attendance.date >= start_date)
    if end_date:
        query = query.where(Attendance.date <= end_date)
    query = query.order_by(Attendance.date.desc(), Employee.full_name_en)
    result = await db.execute(query)
    return list(result.all())


def summarize(rows: list[tuple[Attendance, Employee, Department]]) -> dict:
    total_days = len(rows)
    total_present = sum(1 for a, _, _ in rows if a.status == AttendanceStatus.PRESENT)
    total_incomplete = sum(1 for a, _, _ in rows if a.status == AttendanceStatus.INCOMPLETE)
    total_absent = sum(1 for a, _, _ in rows if a.status == AttendanceStatus.ABSENT)
    hours = [a.total_hours for a, _, _ in rows if a.total_hours is not None]
    average_hours = round(sum(hours) / len(hours), 2) if hours else 0.0
    return {
        "total_days": total_days,
        "total_present": total_present,
        "total_incomplete": total_incomplete,
        "total_absent": total_absent,
        "average_hours": average_hours,
    }


# --- PDF report ---------------------------------------------------------------
def _styles():
    base = getSampleStyleSheet()
    return {
        "report_title": ParagraphStyle(
            "report_title", parent=base["Title"], fontSize=18, textColor=NAVY, spaceAfter=2, alignment=1
        ),
        "report_subtitle": ParagraphStyle(
            "report_subtitle", parent=base["Normal"], fontSize=11, textColor=MID_GREY, alignment=1, spaceAfter=0
        ),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontSize=9, textColor=MID_GREY, alignment=1),
        "section": ParagraphStyle(
            "section", parent=base["Heading2"], fontSize=13, textColor=colors.white, spaceBefore=0, spaceAfter=0, leading=18
        ),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "note": ParagraphStyle("note", parent=base["Normal"], fontSize=8.5, textColor=MID_GREY, spaceAfter=4),
        "kpi_value": ParagraphStyle(
            "kpi_value", parent=base["Normal"], fontSize=20, textColor=NAVY, alignment=1, fontName="Helvetica-Bold"
        ),
        "kpi_label": ParagraphStyle("kpi_label", parent=base["Normal"], fontSize=8.5, textColor=MID_GREY, alignment=1),
    }


def _col_widths(weights: list[float]) -> list[float]:
    total = sum(weights)
    return [CONTENT_WIDTH * w / total for w in weights]


def _section_header(text: str, styles) -> Table:
    t = Table([[Paragraph(text, styles["section"])]], colWidths=[CONTENT_WIDTH])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t


def _data_table(headers: list[str], rows: list[list], col_widths: list, styles) -> Table:
    header_row = [Paragraph(f"<b>{h}</b>", ParagraphStyle("th", parent=styles["cell"], textColor=colors.white)) for h in headers]
    body = [header_row] + rows
    table = Table(body, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 1), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
            ]
        )
    )
    return table


def _footer(canvas_obj, doc):
    canvas_obj.saveState()
    canvas_obj.setStrokeColor(BORDER)
    canvas_obj.line(MARGIN, 1.1 * cm, PAGE_SIZE[0] - MARGIN, 1.1 * cm)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(MID_GREY)
    canvas_obj.drawString(MARGIN, 0.7 * cm, f"{settings.FACULTY_NAME}  |  {settings.DEVELOPER_CREDIT}")
    canvas_obj.drawRightString(PAGE_SIZE[0] - MARGIN, 0.7 * cm, f"Page {doc.page}")
    canvas_obj.restoreState()


async def build_attendance_report_pdf(
    db: AsyncSession,
    *,
    generated_by: Employee,
    start_date: date | None,
    end_date: date | None,
    department_id: int | None,
    employee_id: int | None,
) -> bytes:
    styles = _styles()
    story: list = []

    rows = await get_filtered_attendance(
        db, department_id=department_id, employee_id=employee_id, start_date=start_date, end_date=end_date
    )
    kpis = summarize(rows)

    filter_department = await db.get(Department, department_id) if department_id else None
    filter_employee = await db.get(Employee, employee_id) if employee_id else None
    range_label = f"{start_date.isoformat() if start_date else 'earliest'} → {end_date.isoformat() if end_date else 'latest'}"

    # --- Header ------------------------------------------------------------
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Faculty of Engineering - Attendance Report", styles["report_title"]))
    story.append(Paragraph(settings.FACULTY_NAME, styles["report_subtitle"]))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"Generated: {to_local(now_utc()).strftime('%Y-%m-%d %H:%M %Z')}  |  "
            f"Generated by: {generated_by.full_name_en} ({generated_by.role.value})",
            styles["meta"],
        )
    )
    story.append(
        Paragraph(
            f"Filter range: {range_label}  |  Department: {filter_department.name_en if filter_department else 'All'}"
            f"  |  Employee: {filter_employee.full_name_en if filter_employee else 'All'}",
            styles["meta"],
        )
    )
    story.append(Spacer(1, 12))

    # --- Summary metrics -----------------------------------------------------
    story.append(_section_header("Summary Metrics", styles))
    story.append(Spacer(1, 8))

    def kpi_cell(label, value):
        return [Paragraph(str(value), styles["kpi_value"]), Paragraph(label, styles["kpi_label"])]

    kpi_pairs = [
        kpi_cell("Total Days", kpis["total_days"]),
        kpi_cell("Total Present", kpis["total_present"]),
        kpi_cell("Total Incomplete", kpis["total_incomplete"]),
        kpi_cell("Average Hours", kpis["average_hours"]),
    ]
    values_row = [pair[0] for pair in kpi_pairs]
    labels_row = [pair[1] for pair in kpi_pairs]
    kpi_table = Table([values_row, labels_row], colWidths=_col_widths([1, 1, 1, 1]))
    kpi_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(kpi_table)
    story.append(Spacer(1, 14))

    # --- Detail table ----------------------------------------------------------
    story.append(_section_header("Attendance Log", styles))
    story.append(Spacer(1, 8))

    def fmt_time(dt: datetime | None) -> str:
        local_dt = to_local(dt)
        if not local_dt:
            return "—"
        return local_dt.strftime("%H:%M")

    detail_rows = []
    for a, e, d in rows:
        detail_rows.append(
            [
                Paragraph(a.date.isoformat(), styles["cell"]),
                Paragraph(e.full_name_en, styles["cell"]),
                Paragraph(d.name_en, styles["cell"]),
                Paragraph(fmt_time(a.check_in), styles["cell"]),
                Paragraph(fmt_time(a.check_out), styles["cell"]),
                Paragraph(f"{a.total_hours:.2f}" if a.total_hours is not None else "—", styles["cell"]),
                Paragraph(a.status.value, styles["cell"]),
            ]
        )
    if detail_rows:
        story.append(
            _data_table(
                ["Date", "Employee Name", "Department", "Check-In", "Check-Out", "Total Hours", "Status"],
                detail_rows,
                _col_widths([2.5, 6, 5, 2.5, 2.5, 2.5, 3]),
                styles,
            )
        )
    else:
        story.append(Paragraph("No attendance records match the selected filters.", styles["note"]))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.6 * cm,
        title="Faculty of Engineering - Attendance Report",
        author=settings.DEVELOPER_CREDIT,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
