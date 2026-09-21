import enum


class EmployeeRole(str, enum.Enum):
    """Business role — the source of truth is this field on the Employee
    record (mirrors EFSOP_Directory.Role), never the caller-supplied value.
    ADMIN is a system/technical role for platform administration and is not
    itself a business role in the original design."""

    TEACHING_ASSISTANT = "TeachingAssistant"
    STAFF = "Staff"
    HEAD_OF_DEPARTMENT = "HeadOfDepartment"
    VICE_DEAN = "ViceDean"
    ADMIN = "Admin"


class EmploymentStatus(str, enum.Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"


class LeaveRequestStatus(str, enum.Enum):
    PENDING_STAGE_1 = "PendingStage1"   # awaiting Head of Department
    PENDING_STAGE_2 = "PendingStage2"   # awaiting Vice Dean
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"


class ApprovalStepStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    SKIPPED = "Skipped"


class OfficialDutyStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class NotificationChannel(str, enum.Enum):
    EMAIL = "Email"
    INAPP = "InApp"


class NotificationStatus(str, enum.Enum):
    SENT = "Sent"
    FAILED = "Failed"
    SKIPPED_NO_SMTP = "SkippedNoSmtp"


class AttendanceStatus(str, enum.Enum):
    """Daily check-in/check-out register status. Distinct from the
    OfficialDuty-based "no separate attendance register" position noted
    elsewhere (OD-01) — this module adds an explicit clock-in/out log on
    top of that, per the Attendance Tracking module requirements."""

    PRESENT = "Present"
    INCOMPLETE = "Incomplete"
    ABSENT = "Absent"
