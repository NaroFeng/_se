"""機器人即時狀態快取。

狀態來源有兩種，優先序如下：
  1. ros2-bridge 主動 POST /api/v1/system/heartbeat（延遲最低）
  2. web-backend 背景輪詢 GET /status（Bridge 尚未接上 heartbeat 時的備援）

快取只存在記憶體，重啟後由下一次輪詢重建；歷史紀錄則寫入資料庫。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RobotStateCache:
    """執行緒安全的機器人狀態快取。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: dict[str, Any] = {}
        self._updated_at: datetime | None = None
        self._source: str | None = None

    # ---------------- 寫入 ----------------
    def update(self, status: dict[str, Any], source: str = "heartbeat") -> None:
        with self._lock:
            self._status = dict(status)
            self._status["timestamp"] = (self._status.get("timestamp") or _utcnow().isoformat())
            self._updated_at = _utcnow()
            self._source = source
        logger.debug("機器人狀態已更新（來源：%s）：%s", source, self._status.get("fsm_state"))

    # ---------------- 讀取 ----------------
    @property
    def is_stale(self) -> bool:
        with self._lock:
            return self._is_stale_locked()

    def _is_stale_locked(self) -> bool:
        """呼叫者必須已持有 self._lock（threading.Lock 非重入，不可再取鎖）。"""
        if self._updated_at is None:
            return True
        return (_utcnow() - self._updated_at).total_seconds() > settings.heartbeat_stale_seconds

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._status)
            data["source"] = self._source
            data["updated_at"] = self._updated_at.isoformat() if self._updated_at else None
            data["online"] = not self._is_stale_locked()
            return data

    def clear(self) -> None:
        with self._lock:
            self._status = {}
            self._updated_at = None
            self._source = None


robot_state_cache = RobotStateCache()