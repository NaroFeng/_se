"""ros2-bridge REST 控制埠的 HTTP 客戶端。

web-backend 透過本模組把「呼叫電梯 / 切換地圖 / 開始巡檢」等指令
轉送給 ros2-bridge（Bridge 再 publish 成 ROS 2 topic / service 呼叫）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    """取得共用 HTTP Client（延遲建立）。"""
    global _client
    if _client is None or _client.is_closed:
        async with _lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    base_url=settings.ros_bridge_base_url,
                    timeout=settings.ros_bridge_timeout,
                )
                logger.info("已建立 ros2-bridge HTTP Client：%s", settings.ros_bridge_base_url)
    return _client


async def close_client() -> None:
    """應用程式關閉時釋放連線。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        logger.info("ros2-bridge HTTP Client 已關閉")
    _client = None


async def get_health() -> dict[str, Any]:
    """Bridge 健康檢查；失敗時回傳 reachable=False 而非拋例外。"""
    try:
        client = await get_client()
        resp = await client.get("/health")
        resp.raise_for_status()
        return {"reachable": True, **(resp.json() if resp.content else {})}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ros2-bridge 健康檢查失敗：%s", exc)
        return {"reachable": False, "error": str(exc)}


async def get_status() -> dict[str, Any] | None:
    """取得 Bridge 回報的機器人最新狀態。"""
    try:
        client = await get_client()
        resp = await client.get("/status")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("取得 ros2-bridge 狀態失敗：%s", exc)
        return None


async def send_command(command: str, params: dict[str, Any] | None = None,
                       request_id: str | None = None) -> dict[str, Any]:
    """送出控制指令給 ros2-bridge。"""
    payload: dict[str, Any] = {"command": command, "params": params or {}}
    if request_id:
        payload["request_id"] = request_id

    client = await get_client()
    resp = await client.post("/api/command", json=payload)
    resp.raise_for_status()
    return resp.json()