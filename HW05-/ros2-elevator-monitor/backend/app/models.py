"""SQLAlchemy ORM 資料模型，對應 init-db/01-init.sql 的 Schema。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """宣告式基底類別。"""


class TimestampMixin:
    """建立/更新時間欄位。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="建立時間"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新時間",
    )


# =====================================================================
# 1. 樓層資訊資料表
# =====================================================================
class Floor(TimestampMixin, Base):
    """樓層資訊：地圖路徑、電梯按鈕目標、停靠點位姿。"""

    __tablename__ = "floors"
    __table_args__ = (
        Index("ix_floors_floor_index", "floor_index"),
        Index("ix_floors_active", "is_active", "floor_index"),
        CheckConstraint("floor_index BETWEEN -5 AND 99", name="ck_floors_floor_index"),
        CheckConstraint(
            "(dock_pose IS NULL OR jsonb_typeof(dock_pose) = 'object') AND "
            "(waiting_pose IS NULL OR jsonb_typeof(waiting_pose) = 'object') AND "
            "(nav_goal_pose IS NULL OR jsonb_typeof(nav_goal_pose) = 'object')",
            name="ck_floors_pose_json",
        ),
        {"comment": "樓層資訊資料表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    floor_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, comment="樓層代號 1F/B1")
    floor_index: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="樓層高度序號(地下為負)")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="樓層顯示名稱")
    map_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="ROS 2 地圖名稱")
    map_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="地圖 yaml 路徑")
    map_resolution: Mapped[float] = mapped_column(Float, nullable=False, default=0.05, comment="地圖解析度 m/px")
    has_elevator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否有電梯")
    elevator_id: Mapped[str] = mapped_column(String(32), nullable=False, default="E1", comment="電梯編號")
    elevator_button_target: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="呼叫電梯的目標樓層按鈕"
    )
    dock_pose: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True, comment="停靠點位姿")
    waiting_pose: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True, comment="電梯前等待點位姿")
    nav_goal_pose: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True, comment="巡檢導航目標")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="樓層用途說明")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否啟用")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="排序")

    buttons: Mapped[list["FloorButtonFeature"]] = relationship(
        back_populates="floor",
        cascade="all, delete-orphan",
        lazy="selectin",
        # floor_code 與 target_floor_code 都是 floors 的外鍵，需指定使用哪一個
        foreign_keys="FloorButtonFeature.floor_code",
    )

    def __repr__(self) -> str:  # pragma: no cover - 除錯用
        return f"<Floor {self.floor_code} {self.name}>"


# =====================================================================
# 2. 電梯按鈕座標特徵表
# =====================================================================
class FloorButtonFeature(TimestampMixin, Base):
    """電梯按鈕的影像座標與模板，供 button_recognizer.py 比對。"""

    __tablename__ = "floor_button_features"
    __table_args__ = (
        UniqueConstraint("floor_code", "elevator_id", "button_label", name="uq_button_unique"),
        Index("ix_button_floor", "floor_code", "elevator_id"),
        Index("ix_button_target_floor", "target_floor_code"),
        CheckConstraint("label_width > 0 AND label_height > 0", name="ck_button_bbox"),
        CheckConstraint(
            "center_x BETWEEN 0 AND 1 AND center_y BETWEEN 0 AND 1 "
            "AND norm_width > 0 AND norm_width <= 1 "
            "AND norm_height > 0 AND norm_height <= 1",
            name="ck_button_norm",
        ),
        CheckConstraint(
            "confidence_threshold > 0 AND confidence_threshold <= 1", name="ck_button_threshold"
        ),
        {"comment": "電梯按鈕座標特徵表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    floor_code: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("floors.floor_code", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
        comment="按鈕所在樓層",
    )
    elevator_id: Mapped[str] = mapped_column(String(32), nullable=False, default="E1", comment="電梯編號")
    button_label: Mapped[str] = mapped_column(String(16), nullable=False, comment="按鈕面板文字")
    target_floor_code: Mapped[Optional[str]] = mapped_column(
        String(16),
        ForeignKey("floors.floor_code", onupdate="CASCADE", ondelete="SET NULL"),
        nullable=True,
        comment="按下後預期到達樓層",
    )
    label_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="按鈕框左上 X(px)")
    label_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="按鈕框左上 Y(px)")
    label_width: Mapped[int] = mapped_column(Integer, nullable=False, default=60, comment="按鈕框寬(px)")
    label_height: Mapped[int] = mapped_column(Integer, nullable=False, default=60, comment="按鈕框高(px)")
    center_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, comment="正規化中心 X")
    center_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.5, comment="正規化中心 Y")
    norm_width: Mapped[float] = mapped_column(Float, nullable=False, default=0.08, comment="正規化寬度")
    norm_height: Mapped[float] = mapped_column(Float, nullable=False, default=0.08, comment="正規化高度")
    template_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="模板圖檔路徑")
    confidence_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.75, comment="視覺確認門檻"
    )
    press_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=1200, comment="按壓時間(ms)")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否啟用")

    floor: Mapped["Floor"] = relationship(
        back_populates="buttons",
        foreign_keys="FloorButtonFeature.floor_code",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Button {self.floor_code}/{self.elevator_id}:{self.button_label} -> {self.target_floor_code}>"


# =====================================================================
# 3. 巡檢紀錄日誌表
# =====================================================================
class InspectionLog(Base):
    """跨樓層巡檢事件日誌（FSM 轉移、電梯搭乘、按鈕確認、地圖切換…）。"""

    __tablename__ = "inspection_logs"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('task_start', 'task_finish', 'fsm_transition', 'nav_result', "
            "'elevator_call', 'elevator_enter', 'elevator_exit', 'button_detect', "
            "'button_press', 'map_switch', 'info', 'error')",
            name="ck_logs_event_type",
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed', 'cancelled', 'warning')", name="ck_logs_status"
        ),
        CheckConstraint("log_level IN ('DEBUG', 'INFO', 'WARN', 'ERROR')", name="ck_logs_level"),
        CheckConstraint("detail IS NULL OR jsonb_typeof(detail) = 'object'", name="ck_logs_detail"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_logs_duration"),
        Index("ix_logs_inspection", "inspection_uuid"),
        Index("ix_logs_occurred", "occurred_at"),
        Index("ix_logs_event", "event_type"),
        Index("ix_logs_status", "status"),
        Index("ix_logs_floor", "floor_code"),
        {"comment": "巡檢紀錄日誌表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_uuid: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, comment="巡檢任務識別碼")
    robot_name: Mapped[str] = mapped_column(String(64), nullable=False, default="amr_01", comment="機器人名稱")
    task_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, comment="巡檢任務名稱")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="事件類型")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", comment="事件狀態")
    log_level: Mapped[str] = mapped_column(String(8), nullable=False, default="INFO", comment="日誌等級")
    from_floor_code: Mapped[Optional[str]] = mapped_column(
        String(16),
        ForeignKey("floors.floor_code", onupdate="CASCADE", ondelete="SET NULL", name="fk_logs_from"),
        nullable=True,
        comment="出發樓層",
    )
    to_floor_code: Mapped[Optional[str]] = mapped_column(
        String(16),
        ForeignKey("floors.floor_code", onupdate="CASCADE", ondelete="SET NULL", name="fk_logs_to"),
        nullable=True,
        comment="目標樓層",
    )
    floor_code: Mapped[Optional[str]] = mapped_column(
        String(16),
        ForeignKey("floors.floor_code", onupdate="CASCADE", ondelete="SET NULL", name="fk_logs_floor"),
        nullable=True,
        comment="事件所在樓層",
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="事件描述")
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"), comment="額外資訊"
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="耗時(ms)")
    success: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, comment="是否成功")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="事件發生時間"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="寫入時間"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<InspectionLog {self.inspection_uuid} {self.event_type} {self.status}>"