from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.enums import (
    ApprovalStepStatus,
    EmployeeRole,
    EmploymentStatus,
    LeaveRequestStatus,
    OfficialDutyStatus,
)


# --- Auth ------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Department / Program -----------------------------------------------
class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_en: str
    name_ar: str
    is_active: bool


class DepartmentCreate(BaseModel):
    code: str
    name_en: str
    name_ar: str


# --- Employee ----------------------------------------------------------
class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_code: str
    full_name_en: str
    full_name_ar: str
    email: str
    role: EmployeeRole
    department_id: int
    academic_rank: str | None = None
    employment_status: EmploymentStatus


class EmployeeCreate(BaseModel):
    employee_code: str
    full_name_en: str
    full_name_ar: str
    email: EmailStr
    password: str
    department_id: int
    program_id: int | None = None
    academic_rank: str | None = None
    role: EmployeeRole
    supervisor_id: int | None = None


class EmployeeUpdate(BaseModel):
    full_name_en: str | None = None
    full_name_ar: str | None = None
    email: EmailStr | None = None
    department_id: int | None = None
    program_id: int | None = None
    academic_rank: str | None = None
    role: EmployeeRole | None = None
    employment_status: EmploymentStatus | None = None
    # If set (non-empty), the employee's password is reset to this value.
    # Left unset/blank, the current password is left unchanged.
    new_password: str | None = None


# --- Leave types / balances ----------------------------------------------
class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_en: str
    name_ar: str
    annual_cap: int
    max_consecutive_days: int
    deducts_from_annual: bool
    is_active: bool


class LeaveTypeCreate(BaseModel):
    code: str
    name_en: str
    name_ar: str
    annual_cap: int
    max_consecutive_days: int
    deducts_from_annual: bool = False
    is_active: bool = True


class LeaveTypeUpdate(BaseModel):
    name_en: str | None = None
    name_ar: str | None = None
    annual_cap: int | None = None
    max_consecutive_days: int | None = None
    deducts_from_annual: bool | None = None
    is_active: bool | None = None


class HolidayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    holiday_date: date
    name_en: str
    name_ar: str
    year: int


class HolidayCreate(BaseModel):
    holiday_date: date
    name_en: str
    name_ar: str


class AppSettingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    value: str
    description: str | None = None


class AppSettingUpdate(BaseModel):
    value: str


class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    leave_type_id: int
    year: int
    entitled_days: float
    used_days: float
    pending_days: float

    @property
    def remaining_days(self) -> float:
        return self.entitled_days - self.used_days - self.pending_days


# --- Leave requests -------------------------------------------------------
class LeaveRequestCreate(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    substitute_id: int | None = None
    reason: str
    submission_id: str

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v: str) -> str:
        if len(v.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters.")
        return v


class LeaveDecisionRequest(BaseModel):
    decision: str  # "Approved" | "Rejected"
    note: str | None = None


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_key: str
    applicant_id: int
    leave_type_id: int
    start_date: date
    end_date: date
    working_days: int
    substitute_id: int | None
    reason: str
    status: LeaveRequestStatus
    current_stage: int
    decision_note: str | None
    submitted_at: datetime


# --- Official duties --------------------------------------------------
class OfficialDutyCreate(BaseModel):
    start_date: date
    end_date: date
    destination: str
    purpose: str
    is_retroactive: bool = False
    retro_justification: str | None = None
    evidence_url: str | None = None


class OfficialDutyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    duty_key: str
    owner_id: int
    start_date: date
    end_date: date
    working_days: int
    destination: str
    purpose: str
    is_retroactive: bool
    status: OfficialDutyStatus
    submitted_at: datetime


class DutyDecisionRequest(BaseModel):
    decision: str
    note: str | None = None
