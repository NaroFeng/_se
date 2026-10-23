"""Auth service: mock authentication, role switching, password change."""
import sqlite3
from typing import Any

from flask import session
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config


def _row_to_user(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "department": row["department"],
        "department_id": row["department_id"] if "department_id" in row.keys() else None,
        "email": row["email"] if "email" in row.keys() else None,
        "student_id": row["student_id"] if "student_id" in row.keys() else None,
        "year_enrolled": row["year_enrolled"] if "year_enrolled" in row.keys() else None,
        "section": row["section"] if "section" in row.keys() else None,
        "dept_short_name": row["dept_short_name"] if "dept_short_name" in row.keys() else None,
        "class_name": row["class_name"] if "class_name" in row.keys() else None,
        "role": row["role"],
    }


def find_user_by_username(db: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT u.id, u.username, u.password_hash, u.display_name, u.department, "
        "u.department_id, u.email, u.student_id, u.year_enrolled, u.section, u.role, "
        "u.status, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.username = ?",
        (username,),
    ).fetchone()


def find_user_by_email(db: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT u.id, u.username, u.password_hash, u.display_name, u.department, "
        "u.department_id, u.email, u.student_id, u.year_enrolled, u.section, u.role, "
        "u.status, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()


def find_user_by_id(db: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT u.id, u.username, u.password_hash, u.display_name, u.department, "
        "u.department_id, u.email, u.student_id, u.year_enrolled, u.section, u.role, "
        "u.status, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.id = ?",
        (user_id,),
    ).fetchone()


def find_user_by_login(db: sqlite3.Connection, identifier: str) -> sqlite3.Row | None:
    """Find by username OR email (case-insensitive)."""
    if not identifier:
        return None
    if "@" in identifier:
        return find_user_by_email(db, identifier)
    return find_user_by_username(db, identifier)


def authenticate(db: sqlite3.Connection, identifier: str, password: str) -> dict[str, Any] | None:
    row = find_user_by_login(db, identifier)
    if row is None:
        return None
    if row["status"] != "active":
        return None
    if not check_password_hash(row["password_hash"], password):
        return None
    return _row_to_user(row)


def login_user(user: dict[str, Any]) -> None:
    session[Config.SESSION_USER_KEY] = user["id"]
    session["_user_role_override"] = None


def logout_user() -> None:
    session.pop(Config.SESSION_USER_KEY, None)
    session.pop("_user_role_override", None)


def switch_role_user(role: str) -> dict[str, Any] | None:
    """Demo helper: temporarily switch role for the current session without
    changing the underlying user record."""
    if role not in ("student", "teacher", "admin"):
        return None
    session["_user_role_override"] = role
    return get_current_user()


def get_current_user(db: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    from flask import current_app, has_app_context, g

    if not has_app_context():
        return None
    if db is None:
        db = g.get("db") or current_app.extensions.get("db")
    user_id = session.get(Config.SESSION_USER_KEY)
    if user_id is None or db is None:
        return None
    row = find_user_by_id(db, int(user_id))
    if row is None:
        return None
    user = _row_to_user(row)
    override = session.get("_user_role_override")
    if override:
        user["role"] = override
        user["role_switched"] = True
    else:
        user["role_switched"] = False
    # Add current grade + computed class_name if student
    from .user_service import compute_class_name, compute_grade
    user["current_grade"] = compute_grade(user.get("year_enrolled"), Config.ACADEMIC_YEAR)
    user["class_name"] = compute_class_name(
        user.get("dept_short_name"),
        user.get("year_enrolled"),
        user.get("section"),
        Config.ACADEMIC_YEAR,
    )
    return user


def change_password(
    db: sqlite3.Connection, username: str, old_password: str, new_password: str
) -> tuple[bool, str]:
    row = find_user_by_username(db, username)
    if row is None:
        return False, "找不到使用者"
    if not check_password_hash(row["password_hash"], old_password):
        return False, "舊密碼錯誤"
    if not new_password or len(new_password) < 4:
        return False, "新密碼至少 4 個字元"
    db.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), row["id"]),
    )
    db.commit()
    return True, "密碼更新成功"