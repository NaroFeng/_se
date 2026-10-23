"""Department service: CRUD + listing for 3000+ user scale."""
import sqlite3
from typing import Any


class DepartmentValidationError(ValueError):
    """Raised when department payload fails validation."""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "short_name": row["short_name"],
        "sort_order": row["sort_order"],
    }


def list_departments(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, code, name, short_name, sort_order FROM departments "
        "ORDER BY sort_order, code"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_department(db: sqlite3.Connection, dept_id: int) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, code, name, short_name, sort_order FROM departments WHERE id = ?",
        (dept_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_department_by_code(db: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, code, name, short_name, sort_order FROM departments WHERE code = ?",
        (code,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def _validate_code(value: Any) -> str:
    s = (value or "").strip().upper() if isinstance(value, str) else ""
    if not s:
        raise DepartmentValidationError("系所代碼不可為空")
    if len(s) > 20:
        raise DepartmentValidationError("系所代碼太長（最多 20 字）")
    if not all(c.isalnum() or c in "._-" for c in s):
        raise DepartmentValidationError("系所代碼只能包含英數字、.、_、-")
    return s


def _validate_name(value: Any) -> str:
    s = (value or "").strip() if isinstance(value, str) else ""
    if not s:
        raise DepartmentValidationError("系所名稱不可為空")
    if len(s) > 80:
        raise DepartmentValidationError("系所名稱太長（最多 80 字）")
    return s


def create_department(
    db: sqlite3.Connection,
    *,
    code: str,
    name: str,
    short_name: str | None,
    sort_order: int = 0,
) -> dict[str, Any]:
    code = _validate_code(code)
    name = _validate_name(name)
    if get_department_by_code(db, code):
        raise DepartmentValidationError(f"系所代碼 {code} 已存在")
    cur = db.execute(
        "INSERT INTO departments (code, name, short_name, sort_order) VALUES (?, ?, ?, ?)",
        (code, name, (short_name or "").strip() or None, int(sort_order or 0)),
    )
    db.commit()
    out = get_department(db, cur.lastrowid)
    assert out is not None
    return out


def update_department(
    db: sqlite3.Connection, dept_id: int, payload: dict[str, Any]
) -> dict[str, Any] | None:
    current = get_department(db, dept_id)
    if current is None:
        return None

    fields: dict[str, Any] = {}
    if "code" in payload:
        new_code = _validate_code(payload["code"])
        if new_code != current["code"]:
            existing = get_department_by_code(db, new_code)
            if existing and existing["id"] != dept_id:
                raise DepartmentValidationError(f"系所代碼 {new_code} 已存在")
        fields["code"] = new_code
    if "name" in payload:
        fields["name"] = _validate_name(payload["name"])
    if "short_name" in payload:
        v = payload["short_name"]
        fields["short_name"] = (v.strip() if isinstance(v, str) else None) or None
    if "sort_order" in payload:
        try:
            fields["sort_order"] = int(payload["sort_order"])
        except (TypeError, ValueError):
            raise DepartmentValidationError("sort_order 必須是整數")

    if not fields:
        return current

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    db.execute(
        f"UPDATE departments SET {set_clause} WHERE id = ?",
        list(fields.values()) + [dept_id],
    )
    db.commit()
    return get_department(db, dept_id)


def delete_department(db: sqlite3.Connection, dept_id: int) -> tuple[bool, str]:
    current = get_department(db, dept_id)
    if current is None:
        return False, "找不到系所"
    in_use = db.execute(
        "SELECT COUNT(*) AS c FROM users WHERE department_id = ?", (dept_id,)
    ).fetchone()["c"]
    if in_use > 0:
        return False, f"系所 {current['code']} 仍有 {in_use} 位人員，無法刪除"
    db.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
    db.commit()
    return True, "已刪除"
