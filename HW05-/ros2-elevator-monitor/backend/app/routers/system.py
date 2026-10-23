"""系統 API：健康檢查、機器人即時狀態、指令轉送。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import check_database, get_db
from ..schemas import (
    BridgeHealth,
    CommandRequest,
    CommandResponse,
    HealthResponse,
    RobotHeartbeat,
    RobotStatus,
)
from ..services import ros_bridge
from ..services.robot_state import robot_state_cache

logger = logging.getLogger(__name__)
router = APIRouter(tags=["系統 System"])


# =====================================================================
# 健康檢查
# =====================================================================
@router.get("/health", response_model=HealthResponse, summary="服務健康檢查")
async def health(db: Session = Depends(get_db)) -> HealthResponse:
    """回報後端、資料庫與 ros2-bridge 三者的健康狀態。"""
    db_ok = check_database()
    bridge_raw = await ros_bridge.get_health()

    bridge = BridgeHealth(
        reachable=bool(bridge_raw.get("reachable")),
        base_url=settings.ros_bridge_base_url,
        detail=bridge_raw.get("status") or bridge_raw.get("error"),
        ws_url=settings.ros_bridge_ws_url,
    )
    overall = "ok" if (db_ok and bridge.reachable) else "degraded"
    return HealthResponse(
        status=overall,  # type: ignore[arg-type]
        service="web-backend",
        version=settings.app_version,
        database=db_ok,
        bridge=bridge,
        server_time=datetime.now(timezone.utc),
    )


# =====================================================================
# 機器人即時狀態
# =====================================================================
@router.get("/system/status", response_model=RobotStatus, summary="取得機器人/FSM 即時狀態")
async def get_status(refresh: bool = Query(False, description="true 時強制向 Bridge 重新查詢")) -> RobotStatus:
    """優先讀取快取（Bridge 心跳），必要時即時向 Bridge 查詢。"""
    snapshot = robot_state_cache.snapshot()
    online = bool(snapshot.get("online"))

    if refresh or not online:
        fresh = await ros_bridge.get_status()
        if fresh:
            robot_state_cache.update(fresh, source="poll")
            snapshot = robot_state_cache.snapshot()
            online = True

    if not snapshot and not online:
        return RobotStatus(robot_name="amr_01", fsm_state="OFFLINE", note="尚未收到 ros2-bridge 狀態")

    return RobotStatus(
        robot_name=snapshot.get("robot_name", "amr_01"),
        fsm_state=snapshot.get("fsm_state", "UNKNOWN"),
        current_floor=snapshot.get("current_floor"),
        target_floor=snapshot.get("target_floor"),
        elevator_state=snapshot.get("elevator_state"),
        map_name=snapshot.get("map_name"),
        battery_percent=snapshot.get("battery_percent"),
        mode=snapshot.get("mode"),
        pose=snapshot.get("pose"),
        image_topic=snapshot.get("image_topic"),
        buttons=snapshot.get("buttons") or [],
        note=snapshot.get("note"),
        timestamp=snapshot.get("timestamp"),
    )


@router.post("/system/heartbeat", response_model=RobotStatus, summary="ros2-bridge 主動回報狀態")
async def heartbeat(payload: RobotHeartbeat) -> RobotStatus:
    """Bridge 以 2~5 Hz 週期呼叫此端點，用於前端即時顯示。"""
    data = payload.model_dump(mode="json")
    robot_state_cache.update(data, source="heartbeat")
    return RobotStatus(
        robot_name=payload.robot_name,
        fsm_state=payload.fsm_state,
        current_floor=payload.current_floor,
        target_floor=payload.target_floor,
        elevator_state=payload.elevator_state,
        map_name=payload.map_name,
        battery_percent=payload.battery_percent,
        mode=payload.mode,
        pose=payload.pose,
        image_topic=payload.image_topic,
        buttons=payload.buttons,
        note=payload.note,
        timestamp=payload.timestamp,
    )


@router.get("/system/bridge/health", response_model=BridgeHealth, summary="ros2-bridge 連線狀態")
async def bridge_health() -> BridgeHealth:
    raw = await ros_bridge.get_health()
    return BridgeHealth(
        reachable=bool(raw.get("reachable")),
        base_url=settings.ros_bridge_base_url,
        detail=raw.get("status") or raw.get("error"),
        ws_url=settings.ros_bridge_ws_url,
    )


# =====================================================================
# 指令轉送（web-backend -> ros2-bridge -> ROS 2）
# =====================================================================
@router.post("/system/command", response_model=CommandResponse,
             summary="下達控制指令給 ros2-bridge")
async def send_command(payload: CommandRequest) -> Any:
    """支援指令：start_inspection / goto_floor / stop_inspection /
    switch_map / call_elevator / press_button / reset_fsm
    """
    try:
        result = await ros_bridge.send_command(
            command=payload.command, params=payload.params, request_id=payload.request_id
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"ros2-bridge 回應錯誤：{exc.response.text}",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("無法連線至 ros2-bridge：%s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"無法連線至 ros2-bridge：{settings.ros_bridge_base_url}",
        ) from exc

    return CommandResponse(
        accepted=bool(result.get("accepted", True)),
        command=payload.command,
        request_id=payload.request_id or result.get("request_id"),
        result=result.get("result"),
        message=result.get("message"),
    )


@router.get("/system/info", summary="服務與連線資訊")
async def system_info() -> dict[str, Any]:
    """供前端顯示微服務連線資訊。"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "database": {
            "host": settings.postgres_host,
            "port": settings.postgres_port,
            "name": settings.postgres_db,
        },
        "ros_bridge": {
            "rest_url": settings.ros_bridge_base_url,
            "ws_url": settings.ros_bridge_ws_url,
        },
        "heartbeat_stale_seconds": settings.heartbeat_stale_seconds,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }