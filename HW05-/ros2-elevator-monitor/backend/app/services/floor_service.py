"""樓層資料存取 helpers。

注意：`floors` 資料表的主鍵是自增 `id`，而 API 一律以 `floor_code`（如 1F/B1）
作為識別碼，因此不可使用 `db.get(Floor, "1F")`，必須以條件查詢取得。
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Floor


def get_floor_by_code(db: Session, floor_code: str) -> Optional[Floor]:
    """依樓層代號取得樓層；不存在回傳 None。"""
    return db.execute(
        select(Floor).where(Floor.floor_code == floor_code)
    ).scalar_one_or_none()


def floor_exists(db: Session, floor_code: str) -> bool:
    """樓層代號是否存在。"""
    return get_floor_by_code(db, floor_code) is not None


def require_floor(db: Session, floor_code: str) -> Floor:
    """依樓層代號取得樓層；不存在時拋出 404。"""
    floor = get_floor_by_code(db, floor_code)
    if floor is None:
        raise HTTPException(status_code=404, detail=f"查無樓層：{floor_code}")
    return floor


def ensure_floor_exists(db: Session, floor_code: str) -> None:
    """檢查樓層代號；不存在時拋出 422（供日誌寫入前檢查 FK）。"""
    if not floor_exists(db, floor_code):
        raise HTTPException(status_code=422, detail=f"查無樓層代號：{floor_code}")