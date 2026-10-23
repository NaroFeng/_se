#!/usr/bin/env python3
"""fsm_node：跨樓層巡檢狀態機（Finite State Machine）。

狀態流程
--------
    IDLE ─► APPROACHING_ELEVATOR ─► WAITING_ELEVATOR ─► ENTERING_ELEVATOR
         ─► MOVING_FLOOR ─► EXITING_ELEVATOR ─► INSPECTING ─► IDLE

Topic 介面
----------
訂閱 ``/inspection/command``
    由 bridge_rest_node 發佈的 JSON 指令，支援：
    ``start_inspection`` / ``goto_floor`` / ``stop_inspection`` /
    ``switch_map`` / ``call_elevator`` / ``press_button`` / ``reset_fsm``

訂閱 ``/elevator/button/result``
    button_recognizer 回報的視覺／觸覺雙重確認結果。

發佈 ``/robot_status``
    即時狀態（current_state / current_floor / battery / error_code…），
    bridge_rest_node 訂閱此 topic 並提供給 Web 前端。

發佈 ``/inspection/event_log``
    每個狀態轉移與關鍵事件都會產生一筆巡檢日誌。

模擬支援
--------
``SIMULATION_MODE=true``（預設）時，感測器（電梯門、車廂、樓層抵達）
由本節點內部模擬產生，讓完整巡檢流程可無實體設備自動示範。
"""

from __future__ import annotations

import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .common import (
    Config,
    ErrorCode,
    EventType,
    TOPIC_BUTTON_REQUEST,
    TOPIC_BUTTON_RESULT,
    TOPIC_CMD_VEL,
    TOPIC_COMMAND,
    TOPIC_EVENT_LOG,
    TOPIC_ELEVATOR_STATE,
    TOPIC_ROBOT_STATUS,
    TOPIC_SCAN,
)
from .central_knowledge import knowledge
from .hardware_hal import HardwareMode, get_hal, get_hardware_mode


class State(Enum):
    """巡檢狀態機的狀態定義。"""

    IDLE = "IDLE"
    APPROACHING_ELEVATOR = "APPROACHING_ELEVATOR"
    WAITING_ELEVATOR = "WAITING_ELEVATOR"
    ENTERING_ELEVATOR = "ENTERING_ELEVATOR"
    MOVING_FLOOR = "MOVING_FLOOR"
    EXITING_ELEVATOR = "EXITING_ELEVATOR"
    INSPECTING = "INSPECTING"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


# 允許的狀態轉移表（用於合法性檢查與記錄）
TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.APPROACHING_ELEVATOR, State.ERROR},
    State.APPROACHING_ELEVATOR: {State.WAITING_ELEVATOR, State.ERROR, State.IDLE},
    State.WAITING_ELEVATOR: {
        State.ENTERING_ELEVATOR, State.APPROACHING_ELEVATOR, State.ERROR, State.IDLE,
    },
    State.ENTERING_ELEVATOR: {State.MOVING_FLOOR, State.ERROR, State.IDLE},
    State.MOVING_FLOOR: {State.EXITING_ELEVATOR, State.ERROR, State.IDLE},
    State.EXITING_ELEVATOR: {
        State.INSPECTING, State.APPROACHING_ELEVATOR, State.ERROR, State.IDLE,
    },
    State.INSPECTING: {State.IDLE, State.APPROACHING_ELEVATOR, State.ERROR},
    State.PAUSED: {State.IDLE},
    State.ERROR: {State.IDLE, State.APPROACHING_ELEVATOR},
}


class FsmNode(Node):
    """跨樓層巡檢狀態機節點。"""

    def __init__(self) -> None:
        super().__init__("fsm_node")

        self._sim = Config.SIMULATION_MODE
        self._rng = random.Random()

        # 硬體抽象層（WP 0）：底盤移動與電梯感知委派至此，
        # 狀態機邏輯本身完全不需因應實體硬體而修改。
        self._hal = get_hal()
        self._hw_mode = get_hardware_mode()

        # ---------------- 狀態 ----------------
        self._state = State.IDLE
        self._prev_state = State.IDLE
        self._resume_state: Optional[State] = None
        self._state_entered_at = time.monotonic()
        self._lock = threading.RLock()

        self._current_floor = Config.DEFAULT_START_FLOOR
        self._target_floor: Optional[str] = None
        self._waypoints: list[str] = []
        self._waypoint_idx = -1
        self._battery = 100.0
        self._error_code = ErrorCode.NONE
        self._error_message: Optional[str] = None
        self._elevator_state = "IDLE"
        self._map_name = f"building_{Config.DEFAULT_START_FLOOR.lower()}"
        self._inspection_uuid = str(uuid.uuid4())
        self._task_name: Optional[str] = None
        self._retry_count = 0
        self._max_retry = 3

        # ---- 中央大腦知識（執行前動態拉取，非寫死）----
        self._floor_knowledge: dict[str, dict[str, Any]] = {}
        self._button_policy: dict[str, Any] = {
            "confidence_threshold": Config.VISION_CONFIDENCE_THRESHOLD,
            "press_duration_ms": Config.PRESS_DURATION_MS,
            "template_path": None,
            "source": "local_default",
        }

        # 按鈕確認的暫存結果
        self._pending_request_id: Optional[str] = None
        self._button_result: Optional[dict[str, Any]] = None

        # ---------------- ROS 介面 ----------------
        self._status_pub = self.create_publisher(String, TOPIC_ROBOT_STATUS, 10)
        self._event_pub = self.create_publisher(String, TOPIC_EVENT_LOG, 20)
        self._button_req_pub = self.create_publisher(String, TOPIC_BUTTON_REQUEST, 10)

        self.create_subscription(String, TOPIC_COMMAND, self._on_command, 10)
        self.create_subscription(String, TOPIC_BUTTON_RESULT, self._on_button_result, 10)

        # ---- 麥克納姆輪底盤：/cmd_vel 發佈與 /scan 訂閱 ----
        self._cmd_vel_pub = self.create_publisher(String, TOPIC_CMD_VEL, 10)
        self._hal.base.set_ros_bridge(
            publish_cmd_vel=lambda data: self._cmd_vel_pub.publish(
                String(data=json.dumps(data))
            ),
        )
        self.create_subscription(String, TOPIC_SCAN, self._on_scan, 5)
        self.create_subscription(String, TOPIC_ELEVATOR_STATE, self._on_elevator_state, 5)

        # 狀態發佈定時器（5 Hz）
        self.create_timer(1.0 / Config.STATUS_PUBLISH_HZ, self._publish_status)
        # 狀態機推進定時器（10 Hz）
        self.create_timer(0.1, self._tick)

        self.get_logger().info(
            f"fsm_node 啟動（模擬模式={self._sim}, "
            f"目前樓層={self._current_floor}, "
            f"按鈕主題={TOPIC_BUTTON_REQUEST}）"
        )

    # =================================================================
    # 硬體抽象層：麥克納姆輪底盤
    # =================================================================
    def _on_scan(self, msg: Any) -> None:
        """接收 LiDAR 掃描資料（real / gazebo 模式判斷電梯門開關）。

        支援兩種輸入：
        * ``sensor_msgs/LaserScan``（Gazebo 中的真實 LiDAR）
        * ``std_msgs/String``（Headless 模式，elevator_sim_node 偽感測器）
        """
        if hasattr(msg, "ranges"):                       # sensor_msgs/LaserScan
            self._hal.base._on_scan(msg)
            return

        try:                                              # std_msgs/String (JSON)
            data = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError):
            return
        self._hal.base._on_scan(data.get("scan", data))

    def _on_elevator_state(self, msg: Any) -> None:
        """接收電梯模擬狀態（Digital Twin）。

        讓底盤能判斷「是否已在車廂內」，避免僅靠 LiDAR 推測。
        """
        try:
            state = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError):
            return
        self._hal.base._in_cabin_hint = bool(state.get("in_cabin"))
        self._elevator_sim = state

    def _on_scan_legacy(self, msg: String) -> None:
        """舊版 scan 處理（保留相容，實際請用 _on_scan）。"""
        try:
            self._hal.base._on_scan(json.loads(msg.data))
        except (json.JSONDecodeError, AttributeError):
            pass

    def _drive_to_elevator_lobby(self) -> None:
        """移動至電梯廳等待點。

        麥克納姆輪底盤：以前進（``linear.x``）前往電梯廳。
        """
        self._hal.base.move(linear_x=0.25, linear_y=0.0, angular_z=0.0)
        time.sleep(Config.SIM_NAV_SEC)
        self._hal.base.stop()

    def _enter_elevator(self) -> None:
        """駛入電梯車廂。

        麥克納姆輪特性：可微幅 ``linear.y`` 平移避免撞擊門框後前進。
        """
        self._hal.base.move(linear_x=0.15, linear_y=0.02, angular_z=0.0)
        door_open = self._hal.base.wait_for_door(timeout_sec=Config.DOOR_WAIT_SEC)
        if not door_open:
            self._fail(ErrorCode.DOOR_TIMEOUT, "等待電梯開門逾時")
            return
        self._hal.base.move(linear_x=0.20, linear_y=0.0, angular_z=0.0)
        time.sleep(Config.SIM_ENTER_SEC)
        self._hal.base.stop()

    def _exit_elevator(self) -> None:
        """駛出電梯並停靠 dock_pose。"""
        door_open = self._hal.base.wait_for_door(timeout_sec=Config.DOOR_WAIT_SEC)
        if not door_open:
            self._fail(ErrorCode.DOOR_TIMEOUT, "電梯門未開啟，無法駛出")
            return
        self._hal.base.move(linear_x=-0.20, linear_y=0.0, angular_z=0.0)
        time.sleep(Config.SIM_EXIT_SEC)
        self._hal.base.stop()

    # =================================================================
    # 指令處理
    # =================================================================
    def _on_command(self, msg: String) -> None:
        """處理 Web 端下達的控制指令。"""
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("無法解析指令 JSON")
            return

        command = payload.get("command")
        params = payload.get("params") or {}
        request_id = payload.get("request_id")

        self.get_logger().info(f"收到指令：{command} params={params}")

        with self._lock:
            if command == "start_inspection":
                self._cmd_start_inspection(params)
            elif command == "goto_floor":
                self._cmd_goto_floor(params)
            elif command == "stop_inspection":
                self._cmd_stop_inspection()
            elif command == "pause":
                self._cmd_pause()
            elif command == "resume":
                self._cmd_resume()
            elif command == "switch_map":
                self._cmd_switch_map(params)
            elif command == "call_elevator":
                self._cmd_call_elevator(params)
            elif command == "press_button":
                self._cmd_press_button(params)
            elif command == "reset_fsm":
                self._cmd_reset_fsm()
            else:
                self.get_logger().warning(f"不支援的指令：{command}")
                self._publish_event(
                    EventType.ERROR, "error",
                    f"不支援的指令：{command}",
                    detail={"request_id": request_id},
                )

    def _cmd_start_inspection(self, params: dict[str, Any]) -> None:
        """開始巡檢任務。"""
        floors = params.get("floors") or params.get("floor")
        if floors is None:
            waypoints = list(Config.DEFAULT_WAYPOINTS)
        elif isinstance(floors, str):
            waypoints = [floors]
        else:
            waypoints = list(floors)

        self._waypoints = waypoints
        self._waypoint_idx = -1
        self._inspection_uuid = str(uuid.uuid4())
        self._task_name = params.get("task_name") or f"巡檢 {' → '.join(waypoints)}"
        self._error_code = ErrorCode.NONE
        self._error_message = None
        self._retry_count = 0

        self._publish_event(
            EventType.TASK_START, "running",
            f"開始巡檢任務：{' → '.join(waypoints)}",
            detail={"waypoints": waypoints, "inspection_uuid": self._inspection_uuid},
        )
        # 前往第一個目標樓層
        self._advance_waypoint()

    def _cmd_goto_floor(self, params: dict[str, Any]) -> None:
        """前往指定樓層。"""
        floor = params.get("floor") or params.get("floor_code")
        if not floor:
            self.get_logger().warning("goto_floor 缺少 floor 參數")
            return
        self._cmd_start_inspection({"floors": [floor], "task_name": f"前往 {floor}"})

    def _cmd_stop_inspection(self) -> None:
        """中止巡檢。"""
        self._publish_event(
            EventType.TASK_FINISH, "cancelled", "巡檢任務被中止",
            detail={"completed_waypoints": self._waypoints[: self._waypoint_idx + 1]},
        )
        with self._lock:
            self._waypoints = []
            self._waypoint_idx = -1
            self._target_floor = None
        self._transition(State.IDLE)

    def _cmd_pause(self) -> None:
        """暫停巡檢（保留目前進度）。"""
        with self._lock:
            if self._state == State.IDLE:
                self.get_logger().warning("目前為 IDLE，無法暫停")
                return
            self._resume_state = self._state
        self._elevator_state = "PAUSED"
        self._publish_event(EventType.INFO, "warning", "巡檢任務已暫停",
                            floor_code=self._current_floor)
        self._transition(State.PAUSED)
        self.get_logger().info("巡檢已暫停")

    def _cmd_resume(self) -> None:
        """恢復暫停中的巡檢。"""
        with self._lock:
            if self._state != State.PAUSED:
                self.get_logger().warning("目前非 PAUSED 狀態，無法恢復")
                return
            resume_to = self._resume_state
            self._resume_state = None
        self._publish_event(EventType.INFO, "success", "巡檢任務已恢復",
                            floor_code=self._current_floor)
        if resume_to:
            self._transition(resume_to)
        self.get_logger().info(f"巡檢已恢復至 {resume_to}")

    def _cmd_switch_map(self, params: dict[str, Any]) -> None:
        """手動切換地圖。"""
        map_name = params.get("map_name")
        if not map_name:
            return
        self._map_name = map_name
        self._publish_event(
            EventType.MAP_SWITCH, "success", f"手動切換地圖：{map_name}",
            detail={"map_name": map_name},
        )

    def _cmd_call_elevator(self, params: dict[str, Any]) -> None:
        """呼叫電梯（不進 elevator 狀態機流程）。"""
        floor = params.get("floor") or params.get("floor_code") or self._current_floor
        self._publish_event(
            EventType.ELEVATOR_CALL, "success", f"呼叫電梯至 {floor}",
            from_floor=self._current_floor, to_floor=floor, floor_code=self._current_floor,
        )
        self._request_button_confirmation(floor)

    def _cmd_press_button(self, params: dict[str, Any]) -> None:
        """手動按壓指定按鈕。"""
        floor = params.get("floor") or self._current_floor
        self._request_button_confirmation(floor, params.get("label"))

    def _cmd_reset_fsm(self) -> None:
        """將狀態機重置為 IDLE。"""
        with self._lock:
            self._error_code = ErrorCode.NONE
            self._error_message = None
            self._retry_count = 0
            self._waypoints = []
            self._waypoint_idx = -1
            self._target_floor = None
            self._elevator_state = "IDLE"
        self._transition(State.IDLE)
        self._publish_event(EventType.INFO, "success", "FSM 已重置為 IDLE")

    # =================================================================
    # 按鈕確認互動
    # =================================================================
    def _request_button_confirmation(
        self, target_floor: str, button_label: Optional[str] = None
    ) -> None:
        """向 button_recognizer 發出視覺／觸覺確認請求。"""
        request_id = uuid.uuid4().hex[:12]
        with self._lock:
            policy = dict(self._button_policy)
        payload = {
            "request_id": request_id,
            "floor_code": self._current_floor,
            "button_label": button_label or target_floor,
            "target_floor": target_floor,
            # 門檻與按壓時間來自中央大腦（自適應學習後的最新值）
            "confidence_threshold": policy.get(
                "confidence_threshold", Config.VISION_CONFIDENCE_THRESHOLD
            ),
            "press_duration_ms": int(policy.get(
                "press_duration_ms", Config.PRESS_DURATION_MS
            )),
            "template_path": policy.get("template_path"),
            "policy_source": policy.get("source", "local_default"),
            # 帶上重試次數：機器人每次調整姿態後重新拍攝，成功率會提升
            "attempt": self._retry_count,
        }
        with self._lock:
            self._pending_request_id = request_id
            self._button_result = None
        self._button_req_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _on_button_result(self, msg: String) -> None:
        """接收 button_recognizer 的確認結果。"""
        try:
            result = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        with self._lock:
            if result.get("request_id") != self._pending_request_id:
                return
            self._button_result = result

        confirmed = bool(result.get("confirmed"))
        vision = result.get("vision") or {}
        tactile = result.get("tactile") or {}

        detail = {
            "request_id": result.get("request_id"),
            # 這三個欄位是中央大腦學習的關鍵訊號
            "attempt": int(result.get("attempt") or 0),
            "vision_confidence": vision.get("confidence"),
            "vision_threshold": vision.get("threshold"),
            "vision_method": vision.get("method"),
            "bbox": vision.get("bbox"),
            "button_label": result.get("button_label"),
            "press_duration_ms": tactile.get("press_duration_ms"),
            "policy_source": result.get("policy_source"),
            "tactile_confirmed": tactile.get("confirmed"),
            "force_kg": tactile.get("force_kg"),
        }

        if confirmed:
            self._publish_event(
                EventType.BUTTON_PRESS, "success",
                f"視覺確認 {result.get('button_label')} 按鈕成功"
                f"（相似度 {vision.get('confidence')}），已按壓 {tactile.get('press_duration_ms')}ms",
                floor_code=self._current_floor,
                to_floor=result.get("target_floor"),
                duration_ms=int(result.get("elapsed_ms") or 0),
                success=True, detail=detail,
            )
        else:
            error_code = int(result.get("error_code") or ErrorCode.LOW_CONFIDENCE)
            self._publish_event(
                EventType.BUTTON_DETECT, "warning",
                f"按鈕確認失敗：{ErrorCode.describe(error_code)}",
                floor_code=self._current_floor,
                duration_ms=int(result.get("elapsed_ms") or 0),
                success=False, detail=detail,
            )

    # =================================================================
    # 狀態機推進
    # =================================================================
    def _advance_waypoint(self) -> None:
        """前往下一個巡檢目標（含中央知識拉取）。"""
        with self._lock:
            self._waypoint_idx += 1
            if self._waypoint_idx >= len(self._waypoints):
                self._publish_event(
                    EventType.TASK_FINISH, "success", "巡檢任務全部完成",
                    detail={"inspection_uuid": self._inspection_uuid,
                            "total_waypoints": len(self._waypoints)},
                )
                self._transition(State.IDLE)
                return
            self._target_floor = self._waypoints[self._waypoint_idx]
            self._retry_count = 0
            same_floor = self._target_floor == self._current_floor

        # ---- 執行前拉取中央知識（地圖 / 位姿 / 按鈕參數）----
        self._pull_central_knowledge()

        if same_floor:
            self._transition(State.INSPECTING)
        else:
            self._transition(State.APPROACHING_ELEVATOR)

    def _pull_central_knowledge(self) -> None:
        """向中央大腦取得目標樓層的地圖、位姿與按鈕參數。

        這讓「更換測試機台」不需要重新調參：新機器人第一次執行
        就會拉到前一台機器人累積的經驗。
        """
        target = self._target_floor
        if not target:
            return

        if not knowledge.enabled:
            return

        floor_info = knowledge.get_floor(target)
        if not floor_info:
            self.get_logger().warn(
                f"中央大腦查無樓層 {target}，沿用本地預設值"
            )
            return

        # 套用地圖名稱
        map_name = floor_info.get("map_name")
        if map_name:
            with self._lock:
                self._map_name = map_name

        # 記錄該樓層位姿（供 APPROACHING / EXITING 狀態使用）
        with self._lock:
            self._floor_knowledge[target] = {
                "map_name": map_name,
                "dock_pose": floor_info.get("dock_pose"),
                "waiting_pose": floor_info.get("waiting_pose"),
                "nav_goal_pose": floor_info.get("nav_goal_pose"),
            }

        # 拉取按鈕參數（中央大腦學習後的最新值）
        button = knowledge.get_button(self._current_floor, target_floor_code=target)
        with self._lock:
            self._button_policy = {
                "confidence_threshold": (button or {}).get(
                    "confidence_threshold", Config.VISION_CONFIDENCE_THRESHOLD
                ),
                "press_duration_ms": int((button or {}).get(
                    "press_duration_ms", Config.PRESS_DURATION_MS
                )),
                "template_path": (button or {}).get("template_path"),
                "source": "central_brain" if button else "local_default",
            }

        self.get_logger().info(
            f"已拉取中央知識 [{target}]：地圖={map_name}、"
            f"門檻={self._button_policy['confidence_threshold']:.3f}、"
            f"按壓={self._button_policy['press_duration_ms']}ms"
            f"（來源：{self._button_policy['source']}）"
        )

    def _tick(self) -> None:
        """狀態機主迴圈（由 10 Hz 定時器驅動）。"""
        with self._lock:
            state = self._state
            elapsed = time.monotonic() - self._state_entered_at
            sim_elapsed = self._simulated_elapsed(state)

        if elapsed < sim_elapsed:
            return

        handler = {
            State.IDLE: self._do_idle,
            State.APPROACHING_ELEVATOR: self._do_approaching,
            State.WAITING_ELEVATOR: self._do_waiting_elevator,
            State.ENTERING_ELEVATOR: self._do_entering,
            State.MOVING_FLOOR: self._do_moving_floor,
            State.EXITING_ELEVATOR: self._do_exiting,
            State.INSPECTING: self._do_inspecting,
            State.PAUSED: self._do_paused,
            State.ERROR: self._do_error,
        }.get(state)

        if handler:
            handler()

    def _simulated_elapsed(self, state: State) -> float:
        """各狀態的模擬執行時間。"""
        return {
            State.APPROACHING_ELEVATOR: 2.0,
            State.WAITING_ELEVATOR: Config.SIM_ELEVATOR_WAIT_SEC,
            State.ENTERING_ELEVATOR: 2.5,
            State.MOVING_FLOOR: Config.SIM_RIDE_SEC,
            State.EXITING_ELEVATOR: 2.5,
            State.INSPECTING: 3.0,
        }.get(state, 0.0)

    # ---------------- 各狀態行為 ----------------
    def _do_idle(self) -> None:
        """待機：等待新指令或電量補充。"""
        self._hal.base.recharge(0.02)
        self._elevator_state = "IDLE"

    def _do_approaching(self) -> None:
        """移動至電梯廳等待點（底盤由 HAL 驅動）。"""
        self._drive_to_elevator_lobby()
        self._hal.base.drain_battery(0.05)
        self._publish_event(
            EventType.NAV_RESULT, "success",
            f"已抵達 {self._current_floor} 電梯廳等待點",
            floor_code=self._current_floor,
            to_floor=self._target_floor,
            duration_ms=2000, success=True,
            detail={"target_floor": self._target_floor},
        )
        self._transition(State.WAITING_ELEVATOR)

    def _do_waiting_elevator(self) -> None:
        """等待電梯：確認按鈕並等待門開。"""
        with self._lock:
            if self._button_result is not None:
                result = self._button_result
                self._button_result = None
                self._pending_request_id = None
            else:
                result = None
                if self._pending_request_id is None and self._target_floor:
                    self._request_button_confirmation(self._target_floor)
                    return

        if result is None:
            return

        if not result.get("confirmed"):
            self._retry_count += 1
            if self._retry_count <= self._max_retry:
                self.get_logger().warn(
                    f"按鈕確認失敗，準備重試（{self._retry_count}/{self._max_retry}）"
                )
                self._transition(State.APPROACHING_ELEVATOR)
            else:
                self._fail(ErrorCode.LOW_CONFIDENCE,
                            f"按鈕確認連續失敗 {self._retry_count} 次")
            return

        # 確認成功 → 電梯已受呼叫，等待開門
        self._elevator_state = "CALLING"
        self._publish_event(
            EventType.ELEVATOR_CALL, "success",
            f"已呼叫電梯至 {self._target_floor}",
            floor_code=self._current_floor, to_floor=self._target_floor, success=True,
        )
        self._transition(State.ENTERING_ELEVATOR)

    def _do_entering(self) -> None:
        """偵測電梯門開啟並駛入車廂（底盤由 HAL 驅動）。"""
        self._elevator_state = "DOOR_OPEN"
        self._enter_elevator()
        self._hal.base.drain_battery(0.03)
        self._publish_event(
            EventType.ELEVATOR_ENTER, "success",
            "偵測到電梯門開啟，機器人已駛入車廂",
            floor_code=self._current_floor, to_floor=self._target_floor,
            duration_ms=2500, success=True,
            detail={"in_cabin_sensor": True},
        )
        self._elevator_state = "IN_CABIN"
        self._transition(State.MOVING_FLOOR)

    def _do_moving_floor(self) -> None:
        """電梯移動中。"""
        self._elevator_state = "MOVING"
        self._hal.base.drain_battery(0.02)
        target = self._target_floor
        # 模擬抵達目標樓層（機率性觸發樓層不符）
        if self._rng.random() < 0.05:
            self._fail(ErrorCode.FLOOR_MISMATCH,
                        f"抵達樓層與目標 {target} 不符")
            return
        self._current_floor = target or self._current_floor
        self._map_name = f"building_{self._current_floor.lower()}"
        self._transition(State.EXITING_ELEVATOR)

    def _do_exiting(self) -> None:
        """駛出電梯並停靠（底盤由 HAL 驅動）。"""
        self._elevator_state = "DOOR_OPEN"
        self._exit_elevator()
        self._publish_event(
            EventType.ELEVATOR_EXIT, "success",
            f"已駛出 {self._current_floor} 電梯並停靠",
            floor_code=self._current_floor, duration_ms=2500, success=True,
            detail={"dock_pose": {"x": 1.0, "y": -1.0, "yaw": 0.0}},
        )
        # 地圖切換
        self._publish_event(
            EventType.MAP_SWITCH, "success",
            f"地圖切換完成：building_{self._current_floor.lower()}",
            floor_code=self._current_floor, duration_ms=1200, success=True,
            detail={"map_name": self._map_name},
        )
        self._elevator_state = "IDLE"
        self._retry_count = 0   # 成功抵達目標樓層，重試計數歸零
        self._transition(State.INSPECTING)

    def _do_inspecting(self) -> None:
        """執行巡檢作業。"""
        self._publish_event(
            EventType.NAV_RESULT, "success",
            f"抵達 {self._current_floor} 巡檢點，開始巡檢",
            floor_code=self._current_floor, duration_ms=3000, success=True,
        )
        self._advance_waypoint()

    def _do_paused(self) -> None:
        """任務暫停。"""
        self._elevator_state = "PAUSED"

    def _do_error(self) -> None:
        """錯誤狀態：等待 reset。"""
        self._elevator_state = "ERROR"

    # =================================================================
    # 狀態轉移與錯誤
    # =================================================================
    def _transition(self, new_state: State) -> None:
        """執行狀態轉移（含合法性檢查與事件記錄）。"""
        with self._lock:
            prev = self._state
            if new_state == prev:
                return
            if new_state not in TRANSITIONS.get(prev, set()):
                self.get_logger().warn(
                    f"非法狀態轉移 {prev.value} → {new_state.value}，已忽略"
                )
                return
            self._prev_state = prev
            self._state = new_state
            self._state_entered_at = time.monotonic()

        if new_state != State.ERROR:
            with self._lock:
                if self._error_code != ErrorCode.NONE:
                    self._error_code = ErrorCode.NONE
                    self._error_message = None

        self._publish_event(
            EventType.FSM_TRANSITION, "success",
            f"狀態轉移：{prev.value} → {new_state.value}",
            floor_code=self._current_floor, to_floor=self._target_floor,
            detail={"from": prev.value, "to": new_state.value,
                    "waypoint_index": self._waypoint_idx},
        )
        self.get_logger().info(f"狀態轉移：{prev.value} → {new_state.value}")

    def _fail(self, error_code: int, message: str) -> None:
        """進入錯誤狀態。"""
        with self._lock:
            self._error_code = error_code
            self._error_message = message
            self._elevator_state = "ERROR"
        self._publish_event(
            EventType.ERROR, "error", message,
            floor_code=self._current_floor, to_floor=self._target_floor,
            success=False, detail={"error_code": error_code},
        )
        self.get_logger().error(f"{message} (error_code={error_code})")
        self._transition(State.ERROR)

    # =================================================================
    # 發佈
    # =================================================================
    def _publish_status(self) -> None:
        """發佈 /robot_status（5 Hz）。"""
        with self._lock:
            payload = {
                "robot_name": Config.ROBOT_NAME,
                "fsm_state": self._state.value,
                "current_state": self._state.value,
                "previous_state": self._prev_state.value,
                "current_floor": self._current_floor,
                "target_floor": self._target_floor,
                "elevator_state": self._elevator_state,
                "map_name": self._map_name,
                "battery_percent": round(self._battery, 1),
                "mode": "auto" if self._sim else "real",
                # 硬體抽象層狀態（WP 0）
                "hardware_mode": self._hw_mode,
                "hardware": self._hal.describe(),
                "pose": {"x": 1.0, "y": -1.0, "yaw": 0.0},
                "image_topic": "/camera/color/image_raw",
                "buttons": [],
                "error_code": self._error_code,
                "error_message": self._error_message,
                "waypoints": list(self._waypoints),
                "waypoint_index": self._waypoint_idx,
                "inspection_uuid": self._inspection_uuid,
                "task_name": self._task_name,
                "simulation": self._sim,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        self._status_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

    def _publish_event(
        self,
        event_type: str,
        status: str,
        message: str,
        floor_code: Optional[str] = None,
        from_floor: Optional[str] = None,
        to_floor: Optional[str] = None,
        duration_ms: Optional[int] = None,
        success: Optional[bool] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        """發佈 /inspection/event_log（JSON，供 bridge 轉送 web-backend）。"""
        payload = {
            "inspection_uuid": self._inspection_uuid,
            "robot_name": Config.ROBOT_NAME,
            "task_name": self._task_name,
            "event_type": event_type,
            "status": status,
            "log_level": "ERROR" if status == "error" else (
                "WARN" if status in ("warning", "cancelled") else "INFO"
            ),
            "floor_code": floor_code,
            "from_floor_code": from_floor,
            "to_floor_code": to_floor,
            "message": message,
            "detail": detail or {},
            "duration_ms": duration_ms,
            "success": success,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        self._event_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))


def main(args: Optional[list[str]] = None) -> None:
    """程式進入點。"""
    rclpy.init(args=args)
    node = FsmNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到 Ctrl-C，正在關閉…")
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()