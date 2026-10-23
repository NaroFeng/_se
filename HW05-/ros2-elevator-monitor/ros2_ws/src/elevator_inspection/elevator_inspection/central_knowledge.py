"""中央知識拉取客戶端（Central Knowledge Pull）。

機器人在執行跨樓層任務前，**不信任本地寫死的參數**，
而是從 web-backend（中央大腦）動態取得該樓層的：

* `map_name` / `map_path`          — 該樓層地圖
* `dock_pose` / `waiting_pose`     — 停靠點與電梯廳等待點
* 按鈕的 `confidence_threshold`     — 最新學習後的視覺門檻
* 按鈕的 `press_duration_ms`       — 最新學習後的按壓時間

這使得「更換測試機台」時不必重新調參——
新機器人第一次執行就會拉到前一台累積的經驗。

設計重點
--------
* 採用 **短期記憶體快取 + 背景更新**：避免每個狀態轉移都打 API
* 網路失敗時**退回內建預設值**並記錄警告，確保機器人仍能安全執行
* 使用 `urllib.request`（stdlib）避免額外相依
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Optional


class CentralKnowledge:
    """中央知識快取：保存各樓層的地圖、位姿與按鈕參數。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._floors: dict[str, dict[str, Any]] = {}
        self._buttons: dict[tuple[str, str], dict[str, Any]] = {}
        self._last_fetch: float = 0.0
        self._fetch_failures = 0

        base = os.getenv("BACKEND_BASE_URL", "")
        if not base:
            # 車載邊緣端（docker-compose.edge.yml）使用 BACKEND_URL 指向中央伺服器
            base = os.getenv("BACKEND_URL", "")
        if not base:
            url = os.getenv("BACKEND_CALLBACK_URL", "")
            base = url.split("/api/")[0] if "/api/" in url else ""
        self._base_url = base.rstrip("/")

        # 快取有效時間（秒）；0 表示不快取，每次都拉取
        self._ttl = float(os.getenv("KNOWLEDGE_TTL_SEC", "300"))

    # =================================================================
    # 對外介面
    # =================================================================
    @property
    def enabled(self) -> bool:
        """是否已設定中央大腦網址。"""
        return bool(self._base_url)

    @property
    def base_url(self) -> str:
        return self._base_url

    def get_floor(self, floor_code: str, refresh: bool = False) -> Optional[dict[str, Any]]:
        """取得樓層資訊（含地圖與位姿）。"""
        if not self.enabled:
            return None
        if refresh or self._need_refresh():
            self.refresh()
        with self._lock:
            return self._floors.get(floor_code)

    def get_button(
        self, floor_code: str, target_floor_code: Optional[str] = None,
        button_label: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """取得目標按鈕的最新參數（中央大腦學習後的結果）。"""
        if not self.enabled:
            return None
        if self._need_refresh():
            self.refresh()

        with self._lock:
            for key in (
                (floor_code, button_label or ""),
                (floor_code, target_floor_code or ""),
            ):
                if key[1] and key in self._buttons:
                    return self._buttons[key]

        # 退而求其次：該樓層任一按鈕（僅取門檻/按壓時間的合理預設）
        return None

    def refresh(self) -> bool:
        """強制重新拉取全部知識。"""
        if not self.enabled:
            return False
        try:
            floors = self._http_get("/api/v1/floors")
            if isinstance(floors, list):
                with self._lock:
                    self._floors = {f["floor_code"]: f for f in floors if "floor_code" in f}

            # 逐一拉取按鈕參數（樓層數不多，且有 TTL 快取）
            for floor_code in list(self._floors.keys()):
                buttons = self._http_get(f"/api/v1/floors/{floor_code}/buttons")
                if isinstance(buttons, list):
                    with self._lock:
                        for b in buttons:
                            label = b.get("target_floor_code") or b.get("button_label")
                            if label:
                                self._buttons[(floor_code, label)] = b

            with self._lock:
                self._last_fetch = _now()
                self._fetch_failures = 0
            return True

        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._fetch_failures += 1
            # 首次拉取失敗時告警，之後靜默（避免洗版）
            if self._fetch_failures <= 3:
                _log_warn(f"中央知識拉取失敗（第 {self._fetch_failures} 次）：{exc}")
            return False

    def stats(self) -> dict[str, Any]:
        """供診斷用的統計資訊。"""
        with self._lock:
            return {
                "enabled": self.enabled,
                "base_url": self._base_url,
                "floors_cached": len(self._floors),
                "buttons_cached": len(self._buttons),
                "failures": self._fetch_failures,
            }

    # =================================================================
    # 內部
    # =================================================================
    def _need_refresh(self) -> bool:
        if self._ttl <= 0:
            return True
        with self._lock:
            return (_now() - self._last_fetch) > self._ttl

    def _http_get(self, path: str, timeout: float = 3.0) -> Any:
        url = f"{self._base_url}{path}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


# =====================================================================
# 工具
# =====================================================================
def _now() -> float:
    import time

    return time.monotonic()


def _log_warn(message: str) -> None:
    import sys

    print(f"[central-knowledge] {message}", file=sys.stderr, flush=True)


# 全域單例（fsm_node 與 button_recognizer 共用）
knowledge = CentralKnowledge()