import enum
from sqlalchemy import String, TypeDecorator


class StringEnumType(TypeDecorator):
    """A custom SQLAlchemy TypeDecorator for string-backed Enums that safely delegates
    to Python's Enum class (and its `_missing_` hook) on deserialization."""

    impl = String(64)
    cache_ok = True

    def __init__(self, enum_cls, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enum_cls = enum_cls

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value
        try:
            return self.enum_cls(value)
        except (ValueError, KeyError):
            if hasattr(self.enum_cls, "_missing_"):
                res = self.enum_cls._missing_(value)
                if res is not None:
                    return res
            return list(self.enum_cls)[0]


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

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            if "TEACHING" in val_upper or "TA" == val_upper:
                return cls.TEACHING_ASSISTANT
            if "STAFF" in val_upper:
                return cls.STAFF
            if "HEAD" in val_upper or "HOD" == val_upper:
                return cls.HEAD_OF_DEPARTMENT
            if "VICE" in val_upper or "DEAN" in val_upper:
                return cls.VICE_DEAN
            if "ADMIN" in val_upper:
                return cls.ADMIN
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class EmploymentStatus(str, enum.Enum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class LeaveRequestStatus(str, enum.Enum):
    PENDING = "Pending"
    PENDING_STAGE_1 = "Pending"
    PENDING_STAGE_2 = "Pending"
    APPROVED = "Approved"
    APPROVED_STAGE_1 = "Approved"
    APPROVED_STAGE_2 = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            if "APPROVED" in val_upper:
                return cls.APPROVED
            if "REJECTED" in val_upper:
                return cls.REJECTED
            if "CANCEL" in val_upper:
                return cls.CANCELLED
            if "PENDING" in val_upper:
                return cls.PENDING
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class ApprovalStepStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    SKIPPED = "Skipped"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            if "APPROVED" in val_upper:
                return cls.APPROVED
            if "REJECTED" in val_upper:
                return cls.REJECTED
            if "SKIP" in val_upper:
                return cls.SKIPPED
            if "PENDING" in val_upper:
                return cls.PENDING
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class OfficialDutyStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            if "APPROVED" in val_upper:
                return cls.APPROVED
            if "REJECTED" in val_upper:
                return cls.REJECTED
            if "PENDING" in val_upper:
                return cls.PENDING
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class NotificationChannel(str, enum.Enum):
    EMAIL = "Email"
    INAPP = "InApp"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class NotificationStatus(str, enum.Enum):
    SENT = "Sent"
    FAILED = "Failed"
    SKIPPED_NO_SMTP = "SkippedNoSmtp"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None


class AttendanceStatus(str, enum.Enum):
    """Daily check-in/check-out register status. Distinct from the
    OfficialDuty-based "no separate attendance register" position noted
    elsewhere (OD-01) — this module adds an explicit clock-in/out log on
    top of that, per the Attendance Tracking module requirements."""

    PRESENT = "Present"
    INCOMPLETE = "Incomplete"
    ABSENT = "Absent"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.upper().replace("_", "").replace(" ", "")
            for member in cls:
                if member.value.upper() == val_upper or member.name.upper() == val_upper:
                    return member
        return None

