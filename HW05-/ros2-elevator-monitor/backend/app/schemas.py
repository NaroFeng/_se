"""Pydantic v2 資料傳輸物件（DTO），供 API 請求/回應使用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------
# 列舉型別（與資料庫 CHECK 約束一致）
# --------------------------------------------------------------------
EventType = Literal[
    "task_start", "task_finish", "fsm_transition", "nav_result",
    "elevator_call", "elevator_enter", "elevator_exit",
    "button_detect", "button_press", "map_switch", "info", "error",
]
LogStatus = Literal["running", "success", "failed", "cancelled", "warning"]
LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR"]

EVENT_TYPES: set[str] = set(EventType.__args__)  # type: ignore[attr-defined]
LOG_STATUSES: set[str] = set(LogStatus.__args__)  # type: ignore[attr-defined]
LOG_LEVELS: set[str] = set(LogLevel.__args__)  # type: ignore[attr-defined]


# ====================================================================
# 樓層資訊
# ====================================================================
class FloorBase(BaseModel):
    floor_code: str = Field(..., min_length=1, max_length=16, examples=["3F"], description="樓層代號")
    floor_index: int = Field(..., ge=-5, le=99, examples=[3], description="樓層高度序號（地下為負）")
    name: str = Field(..., max_length=64, examples=["三樓 實驗室"], description="樓層名稱")
    map_name: str = Field(..., max_length=128, examples=["building_3f"], description="ROS 2 地圖名稱")
    map_path: str = Field(..., max_length=255, examples=["/maps/building_3f.yaml"], description="地圖路徑")
    map_resolution: float = Field(default=0.05, gt=0, description="地圖解析度 (m/px)")
    has_elevator: bool = Field(default=True, description="是否設有電梯")
    elevator_id: str = Field(default="E1", max_length=32, description="電梯編號")
    elevator_button_target: Optional[str] = Field(default=None, max_length=16, description="電梯按鈕目標樓層")
    dock_pose: Optional[dict[str, float]] = Field(default=None, description="停靠點位姿 {x,y,yaw}")
    waiting_pose: Optional[dict[str, float]] = Field(default=None, description="電梯前等待點位姿")
    nav_goal_pose: Optional[dict[str, float]] = Field(default=None, description="巡檢導航目標位姿")
    description: Optional[str] = Field(default=None, description="樓層用途說明")
    is_active: bool = Field(default=True, description="是否啟用")
    sort_order: int = Field(default=0, description="排序序號")


class FloorCreate(FloorBase):
    """新增樓層。"""


class FloorUpdate(BaseModel):
    """更新樓層（全部欄位皆為選填，支援部分更新）。"""

    model_config = ConfigDict(extra="forbid")

    floor_code: Optional[str] = Field(default=None, max_length=16)
    floor_index: Optional[int] = Field(default=None, ge=-5, le=99)
    name: Optional[str] = Field(default=None, max_length=64)
    map_name: Optional[str] = Field(default=None, max_length=128)
    map_path: Optional[str] = Field(default=None, max_length=255)
    map_resolution: Optional[float] = Field(default=None, gt=0)
    has_elevator: Optional[bool] = None
    elevator_id: Optional[str] = Field(default=None, max_length=32)
    elevator_button_target: Optional[str] = Field(default=None, max_length=16)
    dock_pose: Optional[dict[str, float]] = None
    waiting_pose: Optional[dict[str, float]] = None
    nav_goal_pose: Optional[dict[str, float]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class FloorRead(FloorBase):
    """查詢結果。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ====================================================================
# 按鈕座標特徵
# ====================================================================
class ButtonFeatureBase(BaseModel):
    button_label: str = Field(..., max_length=16, examples=["5F"], description="按鈕面板文字")
    target_floor_code: Optional[str] = Field(default=None, max_length=16, description="按下後到達樓層")
    label_x: int = Field(default=0, ge=0, description="按鈕框左上 X (px)")
    label_y: int = Field(default=0, ge=0, description="按鈕框左上 Y (px)")
    label_width: int = Field(default=60, gt=0, description="按鈕框寬 (px)")
    label_height: int = Field(default=60, gt=0, description="按鈕框高 (px)")
    center_x: float = Field(default=0.5, ge=0, le=1, description="正規化中心 X")
    center_y: float = Field(default=0.5, ge=0, le=1, description="正規化中心 Y")
    norm_width: float = Field(default=0.08, gt=0, le=1, description="正規化寬度")
    norm_height: float = Field(default=0.08, gt=0, le=1, description="正規化高度")
    template_path: Optional[str] = Field(default=None, max_length=255, description="模板圖檔路徑")
    confidence_threshold: float = Field(default=0.75, gt=0, le=1, description="視覺確認門檻")
    press_duration_ms: int = Field(default=1200, gt=0, description="按壓持續時間 (ms)")
    is_active: bool = Field(default=True)


class ButtonFeatureCreate(ButtonFeatureBase):
    floor_code: str = Field(..., max_length=16, description="按鈕所在樓層")
    elevator_id: str = Field(default="E1", max_length=32)


class ButtonFeatureRead(ButtonFeatureCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ====================================================================
# 巡檢紀錄日誌
# ====================================================================
class InspectionLogCreate(BaseModel):
    """由 ros2-bridge / 機器人節點上報的巡檢事件。

    允許多餘欄位：fsm_node 可能附帶 error_code、waypoints 等額外欄位，
    這些會自動併入 detail 而非被拒絕。
    """

    model_config = ConfigDict(extra="allow")

    inspection_uuid: Optional[UUID] = Field(default=None, description="未指定則自動產生（同一趟巡檢需一致）")
    robot_name: str = Field(default="amr_01", max_length=64)
    task_name: Optional[str] = Field(default=None, max_length=128)
    event_type: EventType = Field(..., description="事件類型")
    status: LogStatus = Field(default="running", description="事件狀態")
    log_level: LogLevel = Field(default="INFO", description="日誌等級")
    from_floor_code: Optional[str] = Field(default=None, max_length=16)
    to_floor_code: Optional[str] = Field(default=None, max_length=16)
    floor_code: Optional[str] = Field(default=None, max_length=16)
    message: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict, description="額外資訊")
    duration_ms: Optional[int] = Field(default=None, ge=0)
    success: Optional[bool] = None
    occurred_at: Optional[datetime] = Field(default=None, description="事件時間（預設取伺服器時間）")

    @field_validator("inspection_uuid", mode="before")
    @classmethod
    def _default_uuid(cls, value: Any) -> Any:
        return value or uuid4()

    @field_validator("occurred_at", mode="before")
    @classmethod
    def _parse_occurred_at(cls, value: Any) -> Any:
        """接受 ISO 8601 字串（含 Z 時區）。"""
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class InspectionLogBatch(BaseModel):
    """FSM 完成一個步驟時批次上報多個事件。"""

    logs: list[InspectionLogCreate] = Field(default_factory=list, max_length=200)


class InspectionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    inspection_uuid: UUID
    robot_name: str
    task_name: Optional[str]
    event_type: str
    status: str
    log_level: str
    from_floor_code: Optional[str]
    to_floor_code: Optional[str]
    floor_code: Optional[str]
    message: Optional[str]
    detail: dict[str, Any]
    duration_ms: Optional[int]
    success: Optional[bool]
    occurred_at: datetime
    created_at: datetime


class InspectionLogPage(BaseModel):
    """分頁查詢結果。"""

    total: int = Field(..., description="符合條件的總筆數")
    limit: int
    offset: int
    items: list[InspectionLogRead]


class InspectionSummary(BaseModel):
    """巡檢統計摘要。"""

    days: int
    total_events: int
    total_inspections: int
    success_inspections: int
    failed_inspections: int
    error_events: int
    success_rate: float = Field(..., description="0~100 的成功率")
    by_event_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_floor: dict[str, int] = Field(default_factory=dict)


class InspectionTaskSummary(BaseModel):
    """單趟巡檢彙總（對應 v_inspection_summary）。"""

    model_config = ConfigDict(from_attributes=True)

    inspection_uuid: UUID
    robot_name: Optional[str]
    task_name: Optional[str]
    started_at: datetime
    finished_at: datetime
    event_count: int
    error_count: int
    has_failed: bool
    all_success: bool
    final_floor_code: Optional[str]


# ====================================================================
# 系統 / 機器人狀態
# ====================================================================
class RobotStatus(BaseModel):
    """ros2-bridge 回報的機器人與 FSM 狀態。"""

    robot_name: str = Field(default="amr_01")
    fsm_state: str = Field(default="IDLE", description="FSM 狀態名稱")
    current_floor: Optional[str] = Field(default=None, description="目前所在樓層")
    target_floor: Optional[str] = Field(default=None, description="目標樓層")
    elevator_state: Optional[str] = Field(default=None, description="電梯狀態")
    map_name: Optional[str] = Field(default=None, description="目前載入的地圖")
    battery_percent: Optional[float] = Field(default=None, ge=0, le=100)
    mode: Optional[str] = Field(default=None, description="執行模式 auto/manual")
    pose: Optional[dict[str, float]] = Field(default=None, description="目前位姿 {x,y,yaw}")
    image_topic: Optional[str] = Field(default=None, description="影像串流 topic")
    buttons: list[dict[str, Any]] = Field(default_factory=list, description="最近按鈕偵測結果")
    note: Optional[str] = None
    timestamp: Optional[datetime] = None


class RobotHeartbeat(RobotStatus):
    """Bridge 主動推播的心跳。"""

    bridge_version: Optional[str] = None


class BridgeHealth(BaseModel):
    reachable: bool
    base_url: str
    detail: Optional[str] = None
    ws_url: Optional[str] = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    database: bool
    bridge: BridgeHealth
    server_time: datetime


class CommandRequest(BaseModel):
    """web-backend 轉送到 ros2-bridge 的控制指令。"""

    command: Literal[
        "start_inspection", "goto_floor", "stop_inspection", "pause", "resume",
        "switch_map", "call_elevator", "press_button", "reset_fsm",
    ] = Field(..., description="指令名稱")
    params: dict[str, Any] = Field(default_factory=dict, description="指令參數")
    request_id: Optional[str] = None


class CommandResponse(BaseModel):
    accepted: bool
    command: str
    request_id: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class FloorRoutePlan(BaseModel):
    """跨樓層路徑規劃結果（供前端顯示或 FSM 使用）。"""

    from_floor: str
    to_floor: str
    same_floor: bool
    needs_elevator: bool
    button_label: Optional[str] = None
    from_floor_info: Optional[FloorRead] = None
    to_floor_info: Optional[FloorRead] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)