"""SQLite connection helpers and schema bootstrap."""
import json
import sqlite3
from pathlib import Path
from typing import Any

from flask import Flask, g

from config import Config


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    student_id TEXT,
    email TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    note TEXT,
    department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL,
    year_enrolled INTEGER,
    section TEXT,
    class_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    short_name TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS menu_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER,
    label TEXT NOT NULL,
    route TEXT,
    icon TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    required_role TEXT NOT NULL DEFAULT 'student',
    FOREIGN KEY (parent_id) REFERENCES menu_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_menu_parent ON menu_items(parent_id);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    author TEXT NOT NULL
);
"""


# Columns added after the initial schema. init_db() ensures they exist on old
# databases via ALTER TABLE ADD COLUMN.
USER_MIGRATIONS = [
    ("student_id", "TEXT"),
    ("email", "TEXT"),
    ("phone", "TEXT"),
    # status is NOT NULL DEFAULT 'active' so existing rows are filled in.
    ("status", "TEXT NOT NULL DEFAULT 'active'"),
    ("note", "TEXT"),
    # updated_at: simple default, NOT CURRENT_TIMESTAMP (SQLite ALTER limitation).
    ("updated_at", "TEXT DEFAULT ''"),
    ("department_id", "INTEGER"),
    ("year_enrolled", "INTEGER"),
    ("section", "TEXT"),
    ("class_name", "TEXT"),
]


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _apply_user_migrations(conn: sqlite3.Connection) -> None:
    for col, decl in USER_MIGRATIONS:
        if not _column_exists(conn, "users", col):
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
    # Backfill status (in case the column was added before the default applied).
    if _column_exists(conn, "users", "status"):
        conn.execute("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''")
    # Indexes — created only after the columns they reference exist.
    if _column_exists(conn, "users", "role"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
    if _column_exists(conn, "users", "status"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
    if _column_exists(conn, "users", "email"):
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE email IS NOT NULL AND email != ''")
    if _column_exists(conn, "users", "department_id"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_department ON users(department_id)")
    if _column_exists(conn, "users", "year_enrolled"):
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_year ON users(year_enrolled)")


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app_db_path())
    return g.db


def current_app_db_path() -> str:
    from flask import current_app
    return current_app.config["DATABASE_PATH"]


def close_db(_exc: Any = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _read_json(path: str) -> Any:
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _seed_users(conn: sqlite3.Connection, path: str) -> None:
    from werkzeug.security import generate_password_hash

    def _derive_email(role, student_id, username, explicit):
        if explicit:
            return explicit.lower()
        if role == "student" and student_id:
            return f"s{student_id}@nqu.edu.tw"
        if username:
            return f"{username}@nqu.edu.tw"
        return None

    data = _read_json(path)
    if not data:
        return
    for u in data:
        # Resolve department code -> id (only when code provided).
        dept_id = None
        code = u.get("department_code")
        if code:
            row = conn.execute(
                "SELECT id FROM departments WHERE code = ?", (code,)
            ).fetchone()
            if row:
                dept_id = row["id"]

        email = _derive_email(
            u["role"], u.get("student_id"), u["username"], u.get("email")
        )

        conn.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, display_name, department, role, "
            "student_id, email, phone, status, note, department_id, year_enrolled, section, class_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                u["username"],
                generate_password_hash(u["password"]),
                u["display_name"],
                u.get("department", ""),
                u["role"],
                u.get("student_id"),
                email,
                u.get("phone"),
                u.get("status", "active"),
                u.get("note"),
                dept_id,
                u.get("year_enrolled"),
                u.get("section"),
                None,  # class_name is computed from short_name + year + section
            ),
        )


def _seed_menu(conn: sqlite3.Connection, path: str) -> None:
    data = _read_json(path)
    if not data:
        return
    cur = conn.cursor()
    cur.execute("DELETE FROM menu_items")
    id_map: dict[str, int] = {}

    def _insert(node: dict, parent_id: int | None) -> None:
        cur.execute(
            "INSERT INTO menu_items (parent_id, label, route, icon, sort_order, required_role) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                parent_id,
                node["label"],
                node.get("route"),
                node.get("icon"),
                node.get("sort_order", 0),
                node.get("required_role", "student"),
            ),
        )
        new_id = cur.lastrowid
        id_map[node["id"]] = new_id
        for child in node.get("children", []):
            _insert(child, new_id)

    for top in data:
        _insert(top, None)


def _seed_announcements(conn: sqlite3.Connection, path: str) -> None:
    data = _read_json(path)
    if not data:
        return
    for a in data:
        conn.execute(
            "INSERT OR IGNORE INTO announcements (slug, title, category, content, issued_at, author) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (a["slug"], a["title"], a["category"], a["content"], a["issued_at"], a["author"]),
        )


def _seed_departments(conn: sqlite3.Connection, path: str) -> None:
    data = _read_json(path)
    if not data:
        return
    for d in data:
        conn.execute(
            "INSERT OR IGNORE INTO departments (code, name, short_name, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (d["code"], d["name"], d.get("short_name"), d.get("sort_order", 0)),
        )


def init_db(app: Flask) -> None:
    db_path = app.config["DATABASE_PATH"]
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _apply_user_migrations(conn)
        _seed_departments(conn, app.config["SEED_DEPARTMENTS_PATH"])
        _seed_users(conn, app.config["SEED_USERS_PATH"])
        _seed_menu(conn, app.config["SEED_MENU_PATH"])
        _seed_announcements(conn, app.config["SEED_ANNOUNCEMENTS_PATH"])
        conn.commit()
    finally:
        conn.close()


def register_db(app: Flask) -> None:
    app.teardown_appcontext(close_db)