"""
Admin comprehensive PDF report.

One button, one PDF: employee directory, department breakdown, leave
balances, the full leave-request log, and the full official-duty log
(the closest thing this system has to attendance/absence — see OD-01 in
docs/BUSINESS_RULES.md, there is no separate daily attendance register).
Built with reportlab/Platypus so long tables paginate automatically.
"""
import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.employee import Employee
from app.models.enums import EmployeeRole, EmploymentStatus, LeaveRequestStatus, OfficialDutyStatus
from app.models.leave import LeaveBalance, LeaveRequest, LeaveType
from app.models.misc import OfficialDuty
from app.models.org import Department

NAVY = colors.HexColor("#1b2a4a")
GOLD = colors.HexColor("#b08d2b")
LIGHT_GREY = colors.HexColor("#f2f3f5")
MID_GREY = colors.HexColor("#6b7280")
BORDER = colors.HexColor("#d7dae0")

PAGE_SIZE = landscape(A4)
MARGIN = 1.4 * cm
CONTENT_WIDTH = PAGE_SIZE[0] - 2 * MARGIN


def _col_widths(weights: list[float]) -> list[float]:
    """Scales relative column weights to sum to exactly CONTENT_WIDTH, so
    every table (and the section-header band) lines up flush with the
    same left/right margins instead of trailing off at an arbitrary width."""
    total = sum(weights)
    return [CONTENT_WIDTH * w / total for w in weights]


def _styles():
    base = getSampleStyleSheet()
    styles = {
        "report_title": ParagraphStyle(
            "report_title", parent=base["Title"], fontSize=20, textColor=NAVY, spaceAfter=2, alignment=1
        ),
        "report_subtitle": ParagraphStyle(
            "report_subtitle", parent=base["Normal"], fontSize=11, textColor=MID_GREY, alignment=1, spaceAfter=0
        ),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontSize=9, textColor=MID_GREY, alignment=1),
        "section": ParagraphStyle(
            "section",
            parent=base["Heading2"],
            fontSize=14,
            textColor=colors.white,
            leftIndent=0,
            spaceBefore=0,
            spaceAfter=0,
            leading=20,
        ),
        "note": ParagraphStyle("note", parent=base["Normal"], fontSize=8.5, textColor=MID_GREY, spaceAfter=4),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=11),
        "cell_bold": ParagraphStyle("cell_bold", parent=base["Normal"], fontSize=8.5, leading=11, fontName="Helvetica-Bold"),
        "kpi_value": ParagraphStyle("kpi_value", parent=base["Normal"], fontSize=20, textColor=NAVY, alignment=1, fontName="Helvetica-Bold"),
        "kpi_label": ParagraphStyle("kpi_label", parent=base["Normal"], fontSize=8.5, textColor=MID_GREY, alignment=1),
    }
    return styles


def _section_header(text: str, styles) -> Table:
    """A full-width navy band, so section headers stay visually anchored
    even though the surrounding content is plain Platypus flow. The navy
    fill is a TableStyle BACKGROUND on the cell (not a Paragraph backColor,
    which only shades the wrapped-text width, not the full column)."""
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
    style = [
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
    table.setStyle(TableStyle(style))
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


async def build_admin_report_pdf(db: AsyncSession, *, generated_by: Employee, year: int | None = None) -> bytes:
    styles = _styles()
    target_year = year or date.today().year
    story: list = []

    # --- Data gathering ------------------------------------------------
    employees_result = await db.execute(select(Employee).order_by(Employee.department_id, Employee.full_name_en))
    employees = employees_result.scalars().all()

    departments_result = await db.execute(select(Department).order_by(Department.name_en))
    departments = departments_result.scalars().all()
    dept_lookup = {d.id: d for d in departments}

    balances_result = await db.execute(
        select(LeaveBalance, LeaveType, Employee)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .join(Employee, Employee.id == LeaveBalance.employee_id)
        .where(LeaveBalance.year == target_year)
        .order_by(Employee.full_name_en, LeaveType.code)
    )
    balances = balances_result.all()

    requests_result = await db.execute(
        select(LeaveRequest, Employee, LeaveType)
        .join(Employee, Employee.id == LeaveRequest.applicant_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .order_by(LeaveRequest.submitted_at.desc())
    )
    leave_requests = requests_result.all()

    duties_result = await db.execute(
        select(OfficialDuty, Employee).join(Employee, Employee.id == OfficialDuty.owner_id).order_by(OfficialDuty.submitted_at.desc())
    )
    duties = duties_result.all()

    # --- KPIs ------------------------------------------------------------
    active_employees = sum(1 for e in employees if e.employment_status == EmploymentStatus.ACTIVE)
    inactive_employees = len(employees) - active_employees

    request_status_counts = {status: 0 for status in LeaveRequestStatus}
    for r, _, _ in leave_requests:
        request_status_counts[r.status] += 1
    total_leave_days_used = sum(b.used_days for b, _, _ in balances)

    duty_status_counts = {status: 0 for status in OfficialDutyStatus}
    retroactive_count = 0
    total_duty_days = 0
    for d, _ in duties:
        duty_status_counts[d.status] += 1
        total_duty_days += d.working_days
        if d.is_retroactive:
            retroactive_count += 1

    # --- Cover / title ---------------------------------------------------
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("EFDP — Employee &amp; Leave Management System", styles["report_title"]))
    story.append(Paragraph("Comprehensive Administrative Report", styles["report_subtitle"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(settings.FACULTY_NAME, styles["meta"]))
    story.append(
        Paragraph(
            f"Reporting year: {target_year}  |  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  |  "
            f"Generated by: {generated_by.full_name_en} ({generated_by.role.value})",
            styles["meta"],
        )
    )
    story.append(Spacer(1, 14))

    # --- Section: Executive summary --------------------------------------
    story.append(_section_header("1. Executive Summary", styles))
    story.append(Spacer(1, 8))

    def kpi_cell(label, value):
        return [Paragraph(str(value), styles["kpi_value"]), Paragraph(label, styles["kpi_label"])]

    kpi_row_1 = [
        kpi_cell("Active Employees", active_employees),
        kpi_cell("Inactive Employees", inactive_employees),
        kpi_cell("Departments", len(departments)),
        kpi_cell("Total Leave Requests", len(leave_requests)),
        kpi_cell("Total Official Duties", len(duties)),
    ]
    # Two-row layout: KPI values on top, labels underneath, side by side.
    values_row = [pair[0] for pair in kpi_row_1]
    labels_row = [pair[1] for pair in kpi_row_1]
    kpi_table = Table([values_row, labels_row], colWidths=_col_widths([1, 1, 1, 1, 1]))
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
    story.append(Spacer(1, 10))

    status_rows = [
        ["Leave Requests — Pending (Stage 1)", str(request_status_counts[LeaveRequestStatus.PENDING_STAGE_1])],
        ["Leave Requests — Pending (Stage 2)", str(request_status_counts[LeaveRequestStatus.PENDING_STAGE_2])],
        ["Leave Requests — Approved", str(request_status_counts[LeaveRequestStatus.APPROVED])],
        ["Leave Requests — Rejected", str(request_status_counts[LeaveRequestStatus.REJECTED])],
        ["Leave Requests — Cancelled", str(request_status_counts[LeaveRequestStatus.CANCELLED])],
        ["Total Leave Days Used (this year)", str(total_leave_days_used)],
        ["Official Duties — Pending", str(duty_status_counts[OfficialDutyStatus.PENDING])],
        ["Official Duties — Approved", str(duty_status_counts[OfficialDutyStatus.APPROVED])],
        ["Official Duties — Rejected", str(duty_status_counts[OfficialDutyStatus.REJECTED])],
        ["Official Duties — Retroactive (late-filed)", str(retroactive_count)],
        ["Total Official Duty Days (away from campus)", str(total_duty_days)],
    ]
    half = (len(status_rows) + 1) // 2
    left_col, right_col = status_rows[:half], status_rows[half:]
    while len(right_col) < len(left_col):
        right_col.append(["", ""])
    combined_rows = [[*l, *r] for l, r in zip(left_col, right_col)]
    summary_table = Table(
        [[Paragraph(str(c), styles["cell"]) for c in row] for row in combined_rows],
        colWidths=_col_widths([3.25, 1, 3.25, 1]),
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT_GREY]),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("ALIGN", (3, 0), (3, -1), "CENTER"),
            ]
        )
    )
    story.append(summary_table)
    story.append(PageBreak())

    # --- Section: Departments --------------------------------------------
    story.append(_section_header("2. Department Breakdown", styles))
    story.append(Spacer(1, 8))
    dept_rows = []
    for d in departments:
        dept_employees = [e for e in employees if e.department_id == d.id]
        head = next((e.full_name_en for e in dept_employees if e.role == EmployeeRole.HEAD_OF_DEPARTMENT and e.employment_status == EmploymentStatus.ACTIVE), "—")
        dept_rows.append(
            [
                Paragraph(d.code, styles["cell_bold"]),
                Paragraph(d.name_en, styles["cell"]),
                Paragraph(str(len(dept_employees)), styles["cell"]),
                Paragraph(str(sum(1 for e in dept_employees if e.employment_status == EmploymentStatus.ACTIVE)), styles["cell"]),
                Paragraph(head, styles["cell"]),
                Paragraph("Active" if d.is_active else "Inactive", styles["cell"]),
            ]
        )
    story.append(
        _data_table(
            ["Code", "Department", "Total Staff", "Active Staff", "Head of Department", "Status"],
            dept_rows,
            _col_widths([2.2, 8, 2.7, 2.7, 6, 2.5]),
            styles,
        )
    )
    story.append(PageBreak())

    # --- Section: Employee directory --------------------------------------
    story.append(_section_header("3. Employee Directory", styles))
    story.append(Spacer(1, 8))
    emp_rows = []
    for e in employees:
        dept = dept_lookup.get(e.department_id)
        emp_rows.append(
            [
                Paragraph(e.employee_code, styles["cell"]),
                Paragraph(e.full_name_en, styles["cell"]),
                Paragraph(e.email, styles["cell"]),
                Paragraph(dept.code if dept else "—", styles["cell"]),
                Paragraph(e.role.value, styles["cell"]),
                Paragraph(e.employment_status.value, styles["cell"]),
            ]
        )
    story.append(
        _data_table(
            ["Code", "Full Name", "Email", "Dept.", "Role", "Status"],
            emp_rows,
            _col_widths([2.5, 6.5, 7.5, 2, 4.5, 2.5]),
            styles,
        )
    )
    story.append(PageBreak())

    # --- Section: Leave balances -------------------------------------------
    story.append(_section_header(f"4. Leave Balances — {target_year}", styles))
    story.append(Spacer(1, 8))
    balance_rows = []
    for b, lt, e in balances:
        balance_rows.append(
            [
                Paragraph(e.full_name_en, styles["cell"]),
                Paragraph(lt.name_en, styles["cell"]),
                Paragraph(str(b.entitled_days), styles["cell"]),
                Paragraph(str(b.used_days), styles["cell"]),
                Paragraph(str(b.pending_days), styles["cell"]),
                Paragraph(str(b.remaining_days), styles["cell_bold"]),
            ]
        )
    if balance_rows:
        story.append(
            _data_table(
                ["Employee", "Leave Type", "Entitled", "Used", "Pending", "Remaining"],
                balance_rows,
                _col_widths([7, 7, 2.5, 2.5, 2.5, 2.5]),
                styles,
            )
        )
    else:
        story.append(Paragraph("No leave balances recorded for this year.", styles["note"]))
    story.append(PageBreak())

    # --- Section: Leave request log -----------------------------------------
    story.append(_section_header("5. Leave Request Log (All Records)", styles))
    story.append(Spacer(1, 8))
    request_rows = []
    for r, e, lt in leave_requests:
        request_rows.append(
            [
                Paragraph(r.request_key, styles["cell"]),
                Paragraph(e.full_name_en, styles["cell"]),
                Paragraph(lt.name_en, styles["cell"]),
                Paragraph(f"{r.start_date} → {r.end_date}", styles["cell"]),
                Paragraph(str(r.working_days), styles["cell"]),
                Paragraph(r.status.value, styles["cell"]),
            ]
        )
    if request_rows:
        story.append(
            _data_table(
                ["Key", "Applicant", "Type", "Dates", "Days", "Status"],
                request_rows,
                _col_widths([3, 6.5, 3, 6, 2, 4]),
                styles,
            )
        )
    else:
        story.append(Paragraph("No leave requests recorded.", styles["note"]))
    story.append(PageBreak())

    # --- Section: Official duties / attendance log ---------------------------
    story.append(_section_header("6. Official Duty Log — Attendance Away From Campus (All Records)", styles))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Note: EFDP does not maintain a separate daily attendance/clock-in register. Official Duty "
            "registrations below are the system's record of approved time spent away from campus "
            "for work purposes, including retroactively filed entries — see docs/BUSINESS_RULES.md (OD-01).",
            styles["note"],
        )
    )
    story.append(Spacer(1, 6))
    duty_rows = []
    for d, e in duties:
        duty_rows.append(
            [
                Paragraph(d.duty_key, styles["cell"]),
                Paragraph(e.full_name_en, styles["cell"]),
                Paragraph(d.destination, styles["cell"]),
                Paragraph(f"{d.start_date} → {d.end_date}", styles["cell"]),
                Paragraph(str(d.working_days), styles["cell"]),
                Paragraph("Yes" if d.is_retroactive else "No", styles["cell"]),
                Paragraph(d.status.value, styles["cell"]),
            ]
        )
    if duty_rows:
        story.append(
            _data_table(
                ["Key", "Employee", "Destination", "Dates", "Days", "Retroactive", "Status"],
                duty_rows,
                _col_widths([2.7, 5.5, 5, 5, 1.8, 2.5, 3]),
                styles,
            )
        )
    else:
        story.append(Paragraph("No official duties recorded.", styles["note"]))

    # --- Build ---------------------------------------------------------------
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.6 * cm,
        title="EFDP Comprehensive Administrative Report",
        author=settings.DEVELOPER_CREDIT,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
