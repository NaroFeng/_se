"""Application configuration."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "nku-secret-dev-key-change-me")
    DATABASE_PATH = os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "instance" / "nku_portal.sqlite")
    )
    SEED_MENU_PATH = str(BASE_DIR / "data" / "seed_menu.json")
    SEED_USERS_PATH = str(BASE_DIR / "data" / "seed_users.json")
    SEED_DEPARTMENTS_PATH = str(BASE_DIR / "data" / "seed_departments.json")
    SEED_ANNOUNCEMENTS_PATH = str(BASE_DIR / "data" / "seed_announcements.json")
    SESSION_USER_KEY = "_user_id"

    # Current academic year (中華民國學年). Used to derive student grade.
    # Override via env: ACADEMIC_YEAR=115
    ACADEMIC_YEAR = int(os.environ.get("ACADEMIC_YEAR", "115"))
    SEMESTER_LABEL = os.environ.get(
        "SEMESTER_LABEL", f"{ACADEMIC_YEAR}學年度第1學期"
    )
    SCHOOL_NAME = os.environ.get("SCHOOL_NAME", "金門大學")
    SYSTEM_NAME = os.environ.get("SYSTEM_NAME", "校務資訊系統")


class TestConfig(Config):
    TESTING = True
    DATABASE_PATH = ":memory:"