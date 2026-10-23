"""Menu service: tree building, role-based filtering, CRUD."""
import sqlite3
from typing import Any

ROLE_RANK = {"student": 0, "teacher": 1, "admin": 2}
VALID_ROLES = set(ROLE_RANK.keys())


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "label": row["label"],
        "route": row["route"],
        "icon": row["icon"],
        "sort_order": row["sort_order"],
        "required_role": row["required_role"],
    }


def fetch_all_menu_items(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, parent_id, label, route, icon, sort_order, required_role "
        "FROM menu_items ORDER BY parent_id IS NULL DESC, sort_order, id"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_menu_item(db: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, parent_id, label, route, icon, sort_order, required_role "
        "FROM menu_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def filter_menu_by_role(
    items: list[dict[str, Any]], role: str
) -> list[dict[str, Any]]:
    """Filter menu items whose required_role is accessible by the given role."""
    user_rank = ROLE_RANK.get(role, 0)
    return [it for it in items if ROLE_RANK.get(it["required_role"], 0) <= user_rank]


def build_menu_tree(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a nested tree structure from flat items."""
    by_id: dict[int, dict[str, Any]] = {}
    for it in items:
        it["children"] = []
        by_id[it["id"]] = it

    roots: list[dict[str, Any]] = []
    for it in items:
        parent = it["parent_id"]
        if parent is None or parent not in by_id:
            roots.append(it)
        else:
            by_id[parent]["children"].append(it)
    return roots


def visible_routes(items: list[dict[str, Any]]) -> set[str]:
    return {it["route"] for it in items if it["route"]}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _descendant_ids(db: sqlite3.Connection, root_id: int) -> set[int]:
    out: set[int] = set()
    stack = [root_id]
    while stack:
        cur = stack.pop()
        children = db.execute(
            "SELECT id FROM menu_items WHERE parent_id = ?", (cur,)
        ).fetchall()
        for c in children:
            cid = c["id"]
            if cid not in out:
                out.add(cid)
                stack.append(cid)
    return out


class MenuValidationError(ValueError):
    """Raised when a menu payload fails validation."""


def _validate_label(label: Any) -> str:
    s = (label or "").strip() if isinstance(label, str) else ""
    if not s:
        raise MenuValidationError("label 不可為空")
    if len(s) > 80:
        raise MenuValidationError("label 太長（最多 80 字）")
    return s


def _validate_role(role: Any) -> str:
    r = (role or "student").strip()
    if r not in VALID_ROLES:
        raise MenuValidationError(f"required_role 必須是 {sorted(VALID_ROLES)} 之一")
    return r


def create_menu_item(
    db: sqlite3.Connection,
    *,
    label: str,
    parent_id: int | None,
    route: str | None,
    icon: str | None,
    sort_order: int,
    required_role: str,
) -> dict[str, Any]:
    label = _validate_label(label)
    required_role = _validate_role(required_role)

    if parent_id is not None:
        if get_menu_item(db, int(parent_id)) is None:
            raise MenuValidationError("parent_id 不存在")

    if route is not None:
        route = route.strip() or None

    cur = db.execute(
        "INSERT INTO menu_items (parent_id, label, route, icon, sort_order, required_role) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (parent_id, label, route, icon, int(sort_order or 0), required_role),
    )
    db.commit()
    item = get_menu_item(db, cur.lastrowid)
    assert item is not None
    return item


def update_menu_item(
    db: sqlite3.Connection, item_id: int, payload: dict[str, Any]
) -> dict[str, Any] | None:
    current = get_menu_item(db, item_id)
    if current is None:
        return None

    fields: dict[str, Any] = {}

    if "label" in payload:
        fields["label"] = _validate_label(payload["label"])
    if "required_role" in payload:
        fields["required_role"] = _validate_role(payload["required_role"])
    if "route" in payload:
        r = payload["route"]
        fields["route"] = (r.strip() if isinstance(r, str) else None) or None
    if "icon" in payload:
        i = payload["icon"]
        fields["icon"] = (i.strip() if isinstance(i, str) else None) or None
    if "sort_order" in payload:
        try:
            fields["sort_order"] = int(payload["sort_order"])
        except (TypeError, ValueError):
            raise MenuValidationError("sort_order 必須是整數")
    if "parent_id" in payload:
        new_pid = payload["parent_id"]
        if new_pid is not None:
            try:
                new_pid = int(new_pid)
            except (TypeError, ValueError):
                raise MenuValidationError("parent_id 必須是整數")
            if new_pid == item_id:
                raise MenuValidationError("節點不能將自己設為 parent")
            descendants = _descendant_ids(db, item_id)
            if new_pid in descendants:
                raise MenuValidationError("不能將節點移至自己的子孫之下")
            if get_menu_item(db, new_pid) is None:
                raise MenuValidationError("parent_id 不存在")
        fields["parent_id"] = new_pid

    if not fields:
        return current

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [item_id]
    db.execute(f"UPDATE menu_items SET {set_clause} WHERE id = ?", values)
    db.commit()
    return get_menu_item(db, item_id)


def delete_menu_item(db: sqlite3.Connection, item_id: int) -> bool:
    current = get_menu_item(db, item_id)
    if current is None:
        return False
    db.execute("DELETE FROM menu_items WHERE id = ?", (item_id,))
    db.commit()
    return True