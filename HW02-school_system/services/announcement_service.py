"""Announcement service: simple CMS storage."""
import sqlite3
from typing import Any


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "slug": row["slug"],
        "title": row["title"],
        "category": row["category"],
        "content": row["content"],
        "issued_at": row["issued_at"],
        "updated_at": row["updated_at"],
        "author": row["author"],
    }


def list_announcements(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, slug, title, category, content, issued_at, updated_at, author "
        "FROM announcements ORDER BY issued_at DESC, id DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_announcement(db: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, slug, title, category, content, issued_at, updated_at, author "
        "FROM announcements WHERE slug = ?",
        (slug,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def upsert_announcement(
    db: sqlite3.Connection,
    *,
    slug: str,
    title: str,
    category: str,
    content: str,
    issued_at: str,
    author: str,
) -> dict[str, Any]:
    db.execute(
        "INSERT INTO announcements (slug, title, category, content, issued_at, author, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(slug) DO UPDATE SET "
        "title=excluded.title, category=excluded.category, content=excluded.content, "
        "issued_at=excluded.issued_at, author=excluded.author, updated_at=CURRENT_TIMESTAMP",
        (slug, title, category, content, issued_at, author),
    )
    db.commit()
    result = get_announcement(db, slug)
    assert result is not None
    return result


def delete_announcement(db: sqlite3.Connection, slug: str) -> bool:
    cur = db.execute("DELETE FROM announcements WHERE slug = ?", (slug,))
    db.commit()
    return cur.rowcount > 0