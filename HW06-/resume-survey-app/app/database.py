"""SQLite 連線與資料表初始化。

使用原生 ``sqlite3`` 模組（不引入 ORM / 遷移工具），對應資料表 ``submissions``。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = BASE_DIR / "data" / "resume.db"
DEFAULT_UPLOAD_DIR = BASE_DIR / "uploads"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS submissions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    email             TEXT    NOT NULL,
    role              TEXT    NOT NULL,
    experience_years  INTEGER NOT NULL,
    bio               TEXT,
    avatar_path       TEXT    NOT NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """開啟 (必要時建立) 一個 SQLite 連線，回傳 ``sqlite3.Row`` 型態的結果。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    """建立資料表（若尚未存在）。"""
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def insert_submission(
    db_path: Path | str,
    *,
    name: str,
    email: str,
    role: str,
    experience_years: int,
    bio: str,
    avatar_path: str,
) -> dict[str, Any]:
    """寫入一筆履歷問卷，回傳完整資料列（含 ``id`` 與 ``created_at``）。"""
    conn = connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO submissions
                (name, email, role, experience_years, bio, avatar_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, email, role, experience_years, bio, avatar_path),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_submissions(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """取得所有履歷問卷，最新提交的排在最前面。"""
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM submissions ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
