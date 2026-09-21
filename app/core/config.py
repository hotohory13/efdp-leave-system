"""
Central configuration.

Every value here that encodes a business rule traces back to an explicit
decision point (``OD-xx``) in the original EFSOP documentation. Where the
source documents left a decision open, the default below states the
assumption in the same place — change it here, not scattered through the
code. See docs/BUSINESS_RULES.md for the full traceability table.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App -------------------------------------------------------------
    APP_NAME: str = "EFDP - Employee & Leave Management System"
    FACULTY_NAME: str = "Faculty of Engineering, Ahram Canadian University"
    DEVELOPER_CREDIT: str = "Developer: ENG. Omar Yasser"
    ENVIRONMENT: str = "development"

    # --- Database ----------------------------------------------------------
    DATABASE_URL: str = "sqlite+aiosqlite:///./efdp.db"

    # --- Auth --------------------------------------------------------------
    SECRET_KEY: str = "insecure-dev-key-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # --- Business rules ------------------------------------------------------
    # Local timezone for display and for bucketing attendance to a calendar
    # day (Attendance Tracking module). Timestamps are still stored in UTC —
    # this only controls what "today" means and how times are shown.
    APP_TIMEZONE: str = "Africa/Cairo"

    # Weekend days as Python weekday() ints (0=Mon..6=Sun). Default is
    # Friday(4)/Saturday(5) — the Egyptian working week. Resolves the
    # working-day calculation dependency noted against OD-04.
    WEEKEND_DAYS: str = "4,5"

    # OD raised in EFDP-LeaveTypes.xlsx: whether عارضة (casual leave) deducts
    # from the annual (اعتيادي) balance was left "Unconfirmed" in the source
    # workbook. Default False matches the shipped seed row. MUST be confirmed
    # against لائحة شؤون العاملين before production use (see OD-03).
    CASUAL_LEAVE_DEDUCTS_FROM_ANNUAL: bool = False

    # OD-02 resolution carried by Part 3 §5.3: two-stage approval,
    # Head of Department -> Vice Dean. Held as configuration (SLA hours)
    # rather than hardcoded, per FR-LV-17 / EFSOP_ApprovalRoutes.
    APPROVAL_STAGE_1_SLA_HOURS: int = 24
    APPROVAL_STAGE_2_SLA_HOURS: int = 24
    APPROVAL_ESCALATION_HOURS: int = 48

    # BR-10 / list validation formula: a rejection must carry a written reason.
    REJECTION_NOTE_MIN_LENGTH: int = 10
    # OD-13 option 2 (adopted): retroactive official-duty registration needs
    # a written justification of at least this many characters.
    RETRO_JUSTIFICATION_MIN_LENGTH: int = 15

    # --- Notifications (Power Automate replacement) -------------------------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "svc-efdp@acu.edu.eg"

    @property
    def weekend_days(self) -> List[int]:
        return [int(x) for x in self.WEEKEND_DAYS.split(",") if x.strip() != ""]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
