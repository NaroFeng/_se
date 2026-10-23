"""User service: CRUD + listing/search + admin password reset + CSV bulk import.

Designed for 3000+ user scale:
  * Lookups by `username` and `email` use the unique indices.
  * `list_users` paginates with LIMIT/OFFSET, filters push down to SQL.
  * `current_grade` is computed on the fly from `year_enrolled` rather than
    stored, so it's always consistent with `Config.ACADEMIC_YEAR`.
  * `bulk_create_users_from_csv` validates each row independently and returns
    per-row results so one bad row doesn't reject the whole batch.
"""
import csv
import io
import re
import sqlite3
from typing import Any

from werkzeug.security import generate_password_hash

VALID_ROLES = {"student", "teacher", "admin"}
VALID_STATUS = {"active", "disabled", "graduated", "suspended"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserValidationError(ValueError):
    """Raised when user payload fails validation."""


def compute_grade(year_enrolled: int | None, current_academic_year: int | None) -> int | None:
    """Derive current grade from enrollment year. Returns None if inputs invalid.

    Grade = (current_year - enrolled_year) + 1
    """
    if year_enrolled is None or current_academic_year is None:
        return None
    diff = current_academic_year - year_enrolled + 1
    if diff < 1 or diff > 7:
        return None
    return diff


# Chinese numerals for grade display (一/二/三/四/五/六/七/八)
_CN_DIGITS = "一二三四五六七八"


def compute_class_name(
    department_short_name: str | None,
    year_enrolled: int | None,
    section: str | None,
    current_academic_year: int | None,
) -> str | None:
    """Compose the human-readable class label, e.g. "資工二A".

    Format: `{short_name}{cn(grade)}{section}`, e.g. 資工 + 二 + A → 資工二A.

    Returns None when any required field is missing or grade is out of range.
    """
    if not (department_short_name and section):
        return None
    grade = compute_grade(year_enrolled, current_academic_year)
    if grade is None or grade < 1 or grade > len(_CN_DIGITS):
        return None
    return f"{department_short_name}{_CN_DIGITS[grade - 1]}{section}"


def _is_email(s: str) -> bool:
    return bool(s and "@" in s and EMAIL_RE.match(s))


# --- Column sets used by SELECT statements ---------------------------------

_USER_COLS = (
    "id", "username", "display_name", "department", "role",
    "student_id", "email", "phone", "status", "note",
    "department_id", "year_enrolled", "class_name",
    "created_at", "updated_at",
)

_JOIN_COLS = _USER_COLS + (
    "dept_code", "dept_name", "dept_short_name",
)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {col: row[col] for col in row.keys()}


# --- Lookups ---------------------------------------------------------------


def get_user(db: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT u.id, u.username, u.display_name, u.department, u.role, u.student_id, "
        "u.email, u.phone, u.status, u.note, u.department_id, u.year_enrolled, u.section, "
        "u.class_name, u.created_at, u.updated_at, "
        "d.code AS dept_code, d.name AS dept_name, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    return _decorate(row, db) if row else None


def get_user_by_username(db: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT u.id, u.username, u.display_name, u.department, u.role, u.student_id, "
        "u.email, u.phone, u.status, u.note, u.department_id, u.year_enrolled, u.section, "
        "u.class_name, u.created_at, u.updated_at, "
        "d.code AS dept_code, d.name AS dept_name, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.username = ?",
        (username,),
    ).fetchone()
    return _decorate(row, db) if row else None


def get_user_by_email(db: sqlite3.Connection, email: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT u.id, u.username, u.display_name, u.department, u.role, u.student_id, "
        "u.email, u.phone, u.status, u.note, u.department_id, u.year_enrolled, u.section, "
        "u.class_name, u.created_at, u.updated_at, "
        "d.code AS dept_code, d.name AS dept_name, d.short_name AS dept_short_name "
        "FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        "WHERE u.email = ? COLLATE NOCASE",
        (email,),
    ).fetchone()
    return _decorate(row, db) if row else None


def _decorate(row: sqlite3.Row | None, db: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Add computed fields (current_grade, class_name) to a user row dict.

    `current_academic_year` is read from app config when available, falling
    back to a hard-coded default if the caller is outside an app context.
    """
    if row is None:
        return None
    d = _row_to_dict(row)
    from flask import has_app_context, current_app
    if has_app_context() and current_app:
        year = current_app.config.get("ACADEMIC_YEAR")
    else:
        from config import Config
        year = Config.ACADEMIC_YEAR
    d["current_grade"] = compute_grade(d.get("year_enrolled"), year)
    d["class_name"] = compute_class_name(
        d.get("dept_short_name"),
        d.get("year_enrolled"),
        d.get("section"),
        year,
    )
    return d


def find_user_by_login(db: sqlite3.Connection, identifier: str) -> dict[str, Any] | None:
    """Find a user by username OR email (login flow)."""
    s = (identifier or "").strip()
    if not s:
        return None
    if _is_email(s):
        return get_user_by_email(db, s)
    return get_user_by_username(db, s)


def _row_full(row: sqlite3.Row, current_year: int) -> dict[str, Any]:
    d = _row_to_dict(row)
    d["current_grade"] = compute_grade(d.get("year_enrolled"), current_year)
    d["class_name"] = compute_class_name(
        d.get("dept_short_name"),
        d.get("year_enrolled"),
        d.get("section"),
        current_year,
    )
    return d


def _row_full_with_year(row: sqlite3.Row, current_year: int) -> dict[str, Any]:
    """Same as _row_full; kept as an alias for clarity in list_users."""
    return _row_full(row, current_year)


# --- Listing ---------------------------------------------------------------


def list_users(
    db: sqlite3.Connection,
    *,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
    department_id: int | None = None,
    year_enrolled: int | None = None,
    page: int = 1,
    per_page: int = 20,
    current_academic_year: int | None = None,
) -> dict[str, Any]:
    """Return paginated users + total count. Designed for 3000+ rows."""
    where, params = [], []
    if search:
        like = f"%{search.strip()}%"
        where.append(
            "(u.username LIKE ? COLLATE NOCASE "
            "OR u.display_name LIKE ? COLLATE NOCASE "
            "OR u.student_id LIKE ? COLLATE NOCASE "
            "OR u.department LIKE ? COLLATE NOCASE "
            "OR u.email LIKE ? COLLATE NOCASE "
            "OR u.class_name LIKE ? COLLATE NOCASE)"
        )
        params += [like] * 6
    if role and role in VALID_ROLES:
        where.append("u.role = ?")
        params.append(role)
    if status and status in VALID_STATUS:
        where.append("u.status = ?")
        params.append(status)
    if department_id is not None:
        where.append("u.department_id = ?")
        params.append(department_id)
    if year_enrolled is not None:
        where.append("u.year_enrolled = ?")
        params.append(year_enrolled)

    clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = db.execute(
        f"SELECT COUNT(*) AS c FROM users u {clause}", params
    ).fetchone()["c"]
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 20)))
    offset = (page - 1) * per_page

    rows = db.execute(
        f"SELECT u.id, u.username, u.display_name, u.department, u.role, u.student_id, "
        f"u.email, u.phone, u.status, u.note, u.department_id, u.year_enrolled, u.class_name, "
        f"u.created_at, u.updated_at, "
        f"d.code AS dept_code, d.name AS dept_name, d.short_name AS dept_short_name "
        f"FROM users u LEFT JOIN departments d ON u.department_id = d.id "
        f"{clause} "
        f"ORDER BY u.role, u.year_enrolled DESC NULLS LAST, u.id "
        f"LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()

    items = [_row_full(r, current_academic_year) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    }


# --- Validation helpers ----------------------------------------------------


def derive_email(role: str, student_id: str | None, username: str | None,
                explicit: str | None = None) -> str | None:
    """Compute the canonical email for a user.

    Policy: NQU students use `s{student_id}@nqu.edu.tw` (the leading `s`
    avoids numeric-prefix issues in some downstream systems). Teachers /
    admins fall back to `{username}@nqu.edu.tw` if no email is provided.

    `explicit` (when supplied) overrides the policy so admins can still set
    a custom address for testing or guest accounts.
    """
    if explicit:
        return explicit.lower()
    if role == "student" and student_id:
        return f"s{student_id}@nqu.edu.tw"
    if username:
        return f"{username}@nqu.edu.tw"
    return None


def _validate_username(value: Any) -> str:
    s = (value or "").strip() if isinstance(value, str) else ""
    if not s:
        raise UserValidationError("帳號不可為空")
    if len(s) > 40:
        raise UserValidationError("帳號太長（最多 40 字）")
    if not s[0].isalpha():
        raise UserValidationError("帳號必須以英文字母開頭")
    if not all(c.isalnum() or c in "._-@" for c in s):
        raise UserValidationError("帳號只能包含英數字、.、_、-、@")
    return s


def _validate_email(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not EMAIL_RE.match(s):
        raise UserValidationError("Email 格式不正確")
    return s.lower()


def _validate_password(value: Any) -> str:
    s = str(value or "")
    if not s:
        raise UserValidationError("密碼不可為空")
    if len(s) < 4:
        raise UserValidationError("密碼至少 4 個字元")
    return s


def _validate_display_name(value: Any) -> str:
    s = (value or "").strip() if isinstance(value, str) else ""
    if not s:
        raise UserValidationError("姓名不可為空")
    if len(s) > 80:
        raise UserValidationError("姓名太長（最多 80 字）")
    return s


def _validate_role(value: Any) -> str:
    r = (value or "student").strip()
    if r not in VALID_ROLES:
        raise UserValidationError(f"角色必須是 {sorted(VALID_ROLES)} 之一")
    return r


def _validate_status(value: Any) -> str:
    s = (value or "active").strip()
    if s not in VALID_STATUS:
        raise UserValidationError(f"狀態必須是 {sorted(VALID_STATUS)} 之一")
    return s


def _validate_year(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise UserValidationError("入學學年必須是整數")
    if n < 80 or n > 200:
        raise UserValidationError("入學學年超出合理範圍")
    return n


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _validate_section(value: Any) -> str | None:
    """Validate class section letter (e.g. A/B/C/D). Optional."""
    if value is None or value == "":
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if len(s) > 4 or not all(c.isalpha() or c.isdigit() for c in s):
        raise UserValidationError("班別格式不正確（例：A、B、A1）")
    return s


def _validate_department_id(db: sqlite3.Connection, value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        did = int(value)
    except (TypeError, ValueError):
        raise UserValidationError("系所 ID 必須是整數")
    row = db.execute("SELECT id FROM departments WHERE id = ?", (did,)).fetchone()
    if not row:
        raise UserValidationError(f"系所 ID {did} 不存在")
    return did


# --- CRUD ------------------------------------------------------------------


def create_user(db: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    username = _validate_username(payload.get("username"))
    password = _validate_password(payload.get("password"))
    display_name = _validate_display_name(payload.get("display_name"))
    role = _validate_role(payload.get("role"))
    status = _validate_status(payload.get("status", "active"))
    department = _opt_str(payload.get("department")) or ""
    student_id = _opt_str(payload.get("student_id"))
    phone = _opt_str(payload.get("phone"))
    note = _opt_str(payload.get("note"))
    year_enrolled = _validate_year(payload.get("year_enrolled"))
    section = _validate_section(payload.get("section"))
    department_id = _validate_department_id(db, payload.get("department_id"))

    # Email: prefer explicit, otherwise derive from student_id/username.
    explicit = _validate_email(payload.get("email"))
    email = derive_email(role, student_id, username, explicit=explicit)

    if get_user_by_username(db, username):
        raise UserValidationError(f"帳號 {username} 已存在")
    if email and get_user_by_email(db, email):
        raise UserValidationError(f"Email {email} 已存在")

    cur = db.execute(
        "INSERT INTO users (username, password_hash, display_name, department, role, "
        "student_id, email, phone, status, note, department_id, year_enrolled, section, class_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (username, generate_password_hash(password), display_name, department, role,
         student_id, email, phone, status, note, department_id, year_enrolled, section, None),
    )
    db.commit()
    return get_user(db, cur.lastrowid)


def update_user(
    db: sqlite3.Connection, user_id: int, payload: dict[str, Any]
) -> dict[str, Any] | None:
    current = get_user(db, user_id)
    if current is None:
        return None

    fields: dict[str, Any] = {}
    if "username" in payload:
        new_username = _validate_username(payload["username"])
        if new_username != current["username"]:
            existing = get_user_by_username(db, new_username)
            if existing and existing["id"] != user_id:
                raise UserValidationError(f"帳號 {new_username} 已存在")
        fields["username"] = new_username
    if "display_name" in payload:
        fields["display_name"] = _validate_display_name(payload["display_name"])
    if "role" in payload:
        fields["role"] = _validate_role(payload["role"])
    if "status" in payload:
        fields["status"] = _validate_status(payload["status"])
    if "department" in payload:
        fields["department"] = _opt_str(payload["department"]) or ""
    if "student_id" in payload:
        fields["student_id"] = _opt_str(payload["student_id"])
    if "email" in payload:
        new_email = _validate_email(payload["email"])
        if new_email != (current.get("email") or None):
            if new_email and get_user_by_email(db, new_email):
                raise UserValidationError(f"Email {new_email} 已存在")
        fields["email"] = new_email
    # If student_id changed and no explicit email supplied, re-derive.
    if "student_id" in fields and "email" not in fields:
        new_role = fields.get("role", current["role"])
        if new_role == "student" and fields["student_id"]:
            fields["email"] = f"s{fields['student_id']}@nqu.edu.tw"
    # If role changed from non-student to student and we have student_id, derive.
    if "role" in fields and "email" not in fields:
        sid = fields.get("student_id", current.get("student_id"))
        if fields["role"] == "student" and sid:
            fields["email"] = f"s{sid}@nqu.edu.tw"
    if "phone" in payload:
        fields["phone"] = _opt_str(payload["phone"])
    if "note" in payload:
        fields["note"] = _opt_str(payload["note"])
    if "year_enrolled" in payload:
        fields["year_enrolled"] = _validate_year(payload["year_enrolled"])
    if "section" in payload:
        fields["section"] = _validate_section(payload["section"])
    if "class_name" in payload:
        # Legacy: class_name is now computed; silently ignore inputs.
        pass
    if "department_id" in payload:
        fields["department_id"] = _validate_department_id(db, payload["department_id"])

    # Refuse to demote the last active admin
    if "role" in fields and current["role"] == "admin" and fields["role"] != "admin":
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()["c"]
        if remaining <= 1:
            raise UserValidationError("不能降級最後一個啟用中的管理員")
    if "status" in fields and current["role"] == "admin" and fields["status"] != "active":
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()["c"]
        if remaining <= 1:
            raise UserValidationError("不能停用最後一個啟用中的管理員")

    if not fields:
        return current

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    db.execute(
        f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        list(fields.values()) + [user_id],
    )
    db.commit()
    return get_user(db, user_id)


def delete_user(db: sqlite3.Connection, user_id: int) -> tuple[bool, str]:
    current = get_user(db, user_id)
    if current is None:
        return False, "找不到使用者"
    if current["role"] == "admin":
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role = 'admin'"
        ).fetchone()["c"]
        if remaining <= 1:
            return False, "不能刪除最後一個管理員"
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return True, "已刪除"


def reset_password(
    db: sqlite3.Connection, user_id: int, new_password: str
) -> dict[str, Any] | None:
    current = get_user(db, user_id)
    if current is None:
        return None
    pwd = _validate_password(new_password)
    db.execute(
        "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (generate_password_hash(pwd), user_id),
    )
    db.commit()
    return current


# ---------------------------------------------------------------------------
# Bulk import / CSV template
# ---------------------------------------------------------------------------


# Canonical header order (also used for the downloadable template).
CSV_HEADERS = (
    "username",
    "password",
    "display_name",
    "department_code",
    "role",
    "student_id",
    "email",
    "phone",
    "year_enrolled",
    "section",
    "status",
    "note",
)

# Rows the importer will accept as-is for any column.
ALIASES = {
    "name": "display_name",
    "department": "department_code",
    "系所": "department_code",
    "系所代碼": "department_code",
    "學號": "student_id",
    "年級": "class_name",  # legacy alias from old templates
    "信箱": "email",
    "電話": "phone",
    "學年": "year_enrolled",
    "班別": "section",
    "角色": "role",
    "狀態": "status",
    "備註": "note",
    "姓名": "display_name",
    "帳號": "username",
    "密碼": "password",
}


def build_csv_template() -> str:
    """Return a UTF-8-with-BOM CSV string with example rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADERS)
    writer.writerow([
        "s114210503", "pass1234", "王小明", "CS", "student",
        "114210503", "", "0912-000-003",
        "114", "A", "active", "示範：批次匯入（Email 會自動帶入 s學號@nqu.edu.tw）",
    ])
    writer.writerow([
        "T010", "pass1234", "陳老師", "EE", "teacher",
        "", "", "082-313-010",
        "", "", "active", "Email 會自動帶入 username@nqu.edu.tw",
    ])
    # BOM so Excel opens it as UTF-8 by default
    return "\ufeff" + buf.getvalue()


def parse_csv(csv_text: str) -> list[dict[str, str]]:
    """Parse a CSV string (with optional BOM) into a list of dict rows.

    Empty lines and rows that are entirely blank are skipped. Header
    normalisation via ALIASES happens here so callers receive canonical
    column names.
    """
    if not csv_text:
        return []
    # strip BOM
    if csv_text.startswith("\ufeff"):
        csv_text = csv_text[1:]
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not raw:
            continue
        # normalise keys
        normalised: dict[str, str] = {}
        for k, v in raw.items():
            key = (k or "").strip()
            if not key:
                continue
            key = ALIASES.get(key, key)
            normalised[key] = (v or "").strip() if isinstance(v, str) else ""
        # skip fully empty rows
        if not any(normalised.values()):
            continue
        rows.append(normalised)
    return rows


def bulk_create_users_from_csv(
    db: sqlite3.Connection,
    csv_text: str,
    *,
    default_password: str | None = None,
    skip_duplicates: bool = True,
) -> dict[str, Any]:
    """Validate and create users row-by-row from a CSV string.

    Returns:
        {
            "total": int,           # rows parsed
            "created": int,         # successfully inserted
            "skipped": int,         # duplicates when skip_duplicates=True
            "errors": int,          # rows that failed validation
            "results": [
                {"row": int, "username": str, "status": "created"|"skipped"|"error",
                 "error": str?},
                ...
            ],
        }
    """
    rows = parse_csv(csv_text)
    results: list[dict[str, Any]] = []
    created = skipped = errors = 0

    for idx, row in enumerate(rows, start=2):  # start=2 because row 1 is header
        # Resolve department_code → department_id
        dept_id = None
        code = row.get("department_code") or row.get("department")
        if code:
            r = db.execute("SELECT id FROM departments WHERE code = ?", (code.strip().upper(),)).fetchone()
            if r:
                dept_id = r["id"]
            else:
                results.append({
                    "row": idx, "username": row.get("username", ""),
                    "status": "error", "error": f"系所代碼 {code} 不存在",
                })
                errors += 1
                continue

        payload = {
            "username": row.get("username", ""),
            "password": row.get("password") or default_password or "",
            "display_name": row.get("display_name", ""),
            "role": row.get("role", "student"),
            "status": row.get("status") or "active",
            "department": row.get("department") or "",
            "department_id": dept_id,
            "student_id": row.get("student_id", ""),
            "email": row.get("email", ""),  # create_user will derive if empty
            "phone": row.get("phone", ""),
            "note": row.get("note", ""),
            "year_enrolled": row.get("year_enrolled", ""),
            "section": row.get("section", ""),
        }

        # Pre-check duplicate
        if skip_duplicates and payload["username"]:
            existing = get_user_by_username(db, payload["username"])
            if existing:
                results.append({
                    "row": idx, "username": payload["username"],
                    "status": "skipped", "error": "帳號已存在",
                })
                skipped += 1
                continue

        try:
            user = create_user(db, payload)
            results.append({
                "row": idx, "username": user["username"],
                "status": "created", "error": None,
            })
            created += 1
        except UserValidationError as e:
            results.append({
                "row": idx, "username": payload["username"] or "",
                "status": "error", "error": str(e),
            })
            errors += 1

    return {
        "total": len(rows),
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "results": results,
    }


def export_users_csv(
    db: sqlite3.Connection,
    *,
    role: str | None = None,
    status: str | None = None,
    department_id: int | None = None,
) -> str:
    """Produce a UTF-8-with-BOM CSV of users (no passwords), filtered optionally."""
    where, params = [], []
    if role:
        where.append("u.role = ?"); params.append(role)
    if status:
        where.append("u.status = ?"); params.append(status)
    if department_id is not None:
        where.append("u.department_id = ?"); params.append(department_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"SELECT u.username, u.display_name, d.code AS dept_code, d.short_name AS dept_short, "
        f"u.role, u.student_id, u.email, u.phone, u.year_enrolled, u.section, "
        f"u.status, u.note "
        f"FROM users u LEFT JOIN departments d ON u.department_id = d.id {clause} "
        f"ORDER BY u.role, u.year_enrolled DESC NULLS LAST, u.id",
        params,
    ).fetchall()
    from config import Config
    current_year = Config.ACADEMIC_YEAR
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "username", "display_name", "department_code", "role", "student_id",
        "email", "phone", "year_enrolled", "section", "class_name", "status", "note",
    ])
    for r in rows:
        cn = compute_class_name(r["dept_short"], r["year_enrolled"], r["section"], current_year)
        writer.writerow([
            r["username"], r["display_name"], r["dept_code"] or "",
            r["role"], r["student_id"] or "", r["email"] or "",
            r["phone"] or "", r["year_enrolled"] if r["year_enrolled"] is not None else "",
            r["section"] or "", cn or "", r["status"], r["note"] or "",
        ])
    return "\ufeff" + buf.getvalue()
