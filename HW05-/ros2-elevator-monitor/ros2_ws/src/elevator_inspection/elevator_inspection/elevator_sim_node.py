"""elevator_sim_node：學校大樓電梯廳模擬環境節點（Digital Twin）。

設計理念（奧卡姆剃刀）
----------------------
刻意**不**在 Gazebo 中做多樓層垂直升降的剛體物理：

* 三層樓高的電梯井需要真實升降機結構，容易出現穿模（機器人穿過地板）
  與不穩定的接觸力學，導致仿真結果不可信
* 專題報告需要的是**可重現、可解釋的端到端閉環**，
  而不是物理真實度

因此採「輕量模擬 + 感測器介面」策略：
電梯的**門開關與樓層切換**由本節點的狀態機決定，
再透過**偽 LiDAR `/scan`** 與**微動開關回饋**讓機器人「感覺到」環境變化。
機器人（`fsm_node`）完全不知道自己對接的是 Gazebo 還是實體硬體——
因為資訊一律透過標準 ROS 2 topic 流動。

狀態機
------
::

    CLOSED ──(收到 press)──► OPENING ──► OPEN
       ▲                                      │
       │                                      │ (機器人進入車廂 → send_close)
       └──── CLOSING ◄── MOVING ◄────────────┘
                                │
                          (到達目標樓層)
                                ▼
                              OPENING ──► OPEN

Topic 介面
----------
訂閱 ``/actuator/cmd``
    來自 ``hardware_hal.ActuatorInterface`` 的按壓指令::

        {"cmd": "press", "duration_ms": 1350}

發佈 ``/actuator/status``
    微動開關（彈簧式）觸發結果::

        {"tactile_ok": true, "actual_ms": 1330, "force_kg": 5.6,
         "sensor": "micro_switch"}

發佈 ``/scan``（``sensor_msgs/LaserScan``）
    偽 LiDAR：正前方淨空距離隨門狀態改變
    （門關 ≈ 1.0m、門開 ≈ 3.5m），讓 ``fsm_node`` 的
    ``WAITING_ELEVATOR → ENTERING_ELEVATOR`` 被真實觸發。

發佈 ``/elevator/sim_state``（``std_msgs/String``，JSON）
    供 ``hardware_hal.MecanumBaseInterface`` 判斷車廂內外。

發佈 ``/camera/color/image_raw``（``sensor_msgs/Image``）
    偽電梯按鈕面板影像：依目標樓層把對應按鈕「點亮」，
    讓視覺辨識在 Gazebo 與 Headless 兩種模式下都能跑。

訂閱 ``/robot_status``
    取得 FSM 目前狀態，據此決定電梯該開門還是關門。

Headless 模式
-------------
``USE_FAKE_SENSORS``（預設 ``true``）時，本節點自行產生
LiDAR 與相機訊息，**完全不依賴 Gazebo**，
因此可直接在無 GUI、無 Gazebo 的環境下做端到端閉環測試。
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

# 狀態廣播用 QoS：reliable + keep_last，避免與未指定 QoS 的發佈端不匹配
QOS_RELIABLE = QoSProfile(
    depth=10,
    history=HistoryPolicy.KEEP_LAST,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
)

# 感測器資料 QoS：best-effort + depth=1（等同 sensor_msgs 的 SensorDataQoS）
# 大尺寸影像必須用此 QoS，reliable 傳輸會阻塞發佈端
QOS_SENSOR = QoSProfile(
    depth=1,
    history=HistoryPolicy.KEEP_LAST,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
)

try:
    from sensor_msgs.msg import Image, LaserScan

    HAS_SENSOR_MSGS = True
except ImportError:  # pragma: no cover
    Image = LaserScan = None  # type: ignore[assignment]
    HAS_SENSOR_MSGS = False


# --------------------------------------------------------------------
# Topic 定義
# --------------------------------------------------------------------
TOPIC_ACTUATOR_CMD = "/actuator/cmd"
TOPIC_ACTUATOR_STATUS = "/actuator/status"
TOPIC_SCAN = "/scan"
TOPIC_SIM_STATE = "/elevator/sim_state"
TOPIC_ROBOT_STATUS = "/robot_status"
TOPIC_CAMERA = "/camera/color/image_raw"
TOPIC_DOOR_CMD = "/elevator/door_cmd"      # 給 Gazebo 門板模型的控制器

# --------------------------------------------------------------------
# 幾何尺度（依學校大樓走廊實測尺度）
# --------------------------------------------------------------------
DOOR_CLOSED_DISTANCE_M = 1.0     # 門關時，機器人 LiDAR 正前方淨空
DOOR_OPEN_DISTANCE_M = 3.5       # 門開時，可看穿至車廂深處
CORRIDOR_SIDE_DISTANCE_M = 2.2   # 走廊側牆距離
CABIN_DEPTH_M = 2.4              # 車廂深度
DOOR_CENTER_WIDTH_M = 1.1        # 門板中央開口寬度

# 按鈕面板幾何（對齊 init-db 的 1920x1080 版面配置）
PANEL_BUTTON_ORDER = ["B2", "B1", "1F", "2F", "3F", "4F", "5F"]
PANEL_BUTTON_W = 64
PANEL_BUTTON_H = 64


class DoorState(Enum):
    """電梯門狀態。"""

    CLOSED = "CLOSED"
    OPENING = "OPENING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    MOVING = "MOVING"     # 門關閉、車廂跨樓移動中


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class ElevatorSimNode(Node):
    """電梯廳模擬環境節點。"""

    def __init__(self) -> None:
        super().__init__("elevator_sim_node")

        # ---------- 設定 ----------
        self.elevator_id = _env("ELEVATOR_ID", "E1")
        self.start_floor = _env("SIM_START_FLOOR", "1F")
        self.current_floor = self.start_floor
        self.pending_floor: Optional[str] = None

        # 時間尺度（Gazebo 時間可能被暫停，故以 wall time 為準）
        self.open_duration = _env_float("SIM_OPEN_SEC", 2.5)
        self.close_duration = _env_float("SIM_CLOSE_SEC", 2.0)
        self.move_duration = _env_float("SIM_MOVE_SEC", 4.0)
        self.call_delay = _env_float("SIM_CALL_DELAY_SEC", 3.0)

        # 是否自行產生 LiDAR / 相機（Headless 模式）
        self.use_fake_sensors = _env("USE_FAKE_SENSORS", "true").lower() == "true"
        # 偽相機解析度與頻率（可調；解析度過大會拖慢 executor）
        self.cam_width = _env_int("SIM_CAMERA_WIDTH", 640)
        self.cam_height = _env_int("SIM_CAMERA_HEIGHT", 360)
        self.cam_hz = _env_float("SIM_CAMERA_HZ", 5.0)
        # 是否驅動 Gazebo 門板模型
        self.drive_gazebo_doors = _env("DRIVE_GAZEBO_DOORS", "false").lower() == "true"

        self._door = DoorState.CLOSED
        self._door_progress = 0.0        # 0=關閉 1=全開
        self._pending_cmd: Optional[dict[str, Any]] = None
        self._in_cabin = False
        self._inspected_floors: list[str] = []
        self._lit_button: Optional[str] = None   # 面板上被點亮的按鈕
        self._pressed_at: Optional[float] = None
        self._robot_state = "IDLE"
        self._press_count = 0
        self._moving_started = time.monotonic()
        self._pending_floor: Optional[str] = None

        # ---------- ROS 介面 ----------
        self._status_pub = self.create_publisher(String, TOPIC_ACTUATOR_STATUS, 10)
        self._state_pub = self.create_publisher(String, TOPIC_SIM_STATE, 10)
        self._door_cmd_pub = self.create_publisher(String, TOPIC_DOOR_CMD, 10)

        self.create_subscription(String, TOPIC_ACTUATOR_CMD, self._on_actuator_cmd, 10)
        # /robot_status 為低頻狀態廣播，採 reliable QoS 避免與發佈端 QoS 不匹配
        # （測試腳本或外部工具發佈時常忘記設定 QoS 而收不到）
        self.create_subscription(
            String, TOPIC_ROBOT_STATUS, self._on_robot_status,
            QOS_RELIABLE,
        )

        if HAS_SENSOR_MSGS and self.use_fake_sensors:
            self._scan_pub = self.create_publisher(LaserScan, TOPIC_SCAN, QOS_RELIABLE)
            # 偽相機每幀約 6MB（1920x1080 BGR），必須用 best-effort + depth=1：
            #   reliable QoS 會讓 DDS 對大訊息分片並阻塞發佈端，
            #   導致整個 executor 被卡住、狀態機實際只有 ~1 Hz。
            self._cam_pub = self.create_publisher(Image, TOPIC_CAMERA, QOS_SENSOR)
        else:
            self._scan_pub = None
            self._cam_pub = None

        # 模擬時鐘（20 Hz）：狀態機 + LiDAR
        self.create_timer(0.05, self._tick)
        # 偽相機獨立時鐘（2 Hz）
        # 1920x1080 BGR 每幀約 6MB，若跟 20 Hz 主迴圈一起發佈會產生
        # 124 MB/s 頻寬壓力，CPU 被飽和導致狀態機實際只有 ~1 Hz，
        # 電梯門開啟極慢。視覺辨識只需數 Hz，故獨立降頻。
        if self._cam_pub is not None:
            self.create_timer(1.0 / max(0.5, self.cam_hz), self._tick_camera)

        self.get_logger().info(
            f"elevator_sim_node 啟動："
            f"電梯={self.elevator_id} 目前樓層={self.current_floor} "
            f"偽感測器={self.use_fake_sensors} Gazebo門板={self.drive_gazebo_doors}"
        )

    # =================================================================
    # ROS 回呼
    # =================================================================
    def _on_actuator_cmd(self, msg: String) -> None:
        """接收推桿按壓指令（來自 HAL 的 ActuatorInterface）。"""
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("無法解析 /actuator/cmd")
            return

        if cmd.get("cmd") != "press":
            return

        # ---- 模擬彈簧微動開關：按壓後觸發 ----
        requested_ms = int(cmd.get("duration_ms", 1200))
        actual_ms = int(requested_ms * 0.97)   # 實際行程略短於請求
        self._press_count += 1
        self._pressed_at = time.monotonic()

        self._status_pub.publish(String(data=json.dumps({
            "tactile_ok": True,
            "actual_ms": actual_ms,
            "force_kg": round(4.5 + (self._press_count % 5) * 0.8, 2),
            "sensor": "micro_switch",
            "elevator_id": self.elevator_id,
            "floor": self.current_floor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)))

        self.get_logger().info(
            f"模擬微動開關觸發（第 {self._press_count} 次）："
            f"requested={requested_ms}ms actual={actual_ms}ms"
        )

        # 按壓目標樓層的按鈕 → 面板點亮該按鈕（供視覺辨識）
        target = cmd.get("target_floor")
        if target:
            self._lit_button = target

        # 依 FSM 狀態決定後續動作
        if self._robot_state in ("WAITING_ELEVATOR", "IDLE"):
            self._pending_cmd = {"action": "call_and_open", "target": target}

    def _on_robot_status(self, msg: String) -> None:
        """接收 FSM 狀態，據此驅動電梯開關門。"""
        try:
            status = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        self._robot_state = status.get("fsm_state", "IDLE")
        hw_mode = (status.get("hardware") or {}).get("hardware_mode")

        # ---- 機器人進入車廂後關門 ----
        if self._robot_state == "ENTERING_ELEVATOR" and self._door in (
            DoorState.OPEN, DoorState.OPENING
        ):
            # 機器人已駛入車廂（車廂感測器確認）
            self._in_cabin = True
            # 直接進入關門，不以 door_progress 為前置條件：
            # 機器人真正駛入時門可能仍在開啟動畫中
            self._door = DoorState.CLOSING
            self._door_progress = min(self._door_progress, 0.95)
            self._publish_door_cmd("close")
            self.get_logger().info("收到 ENTERING_ELEVATOR → 開始關門")

        # ---- 開始跨樓移動 ----
        elif self._robot_state == "MOVING_FLOOR" and self._door in (
            DoorState.CLOSED, DoorState.CLOSING, DoorState.OPENING
        ):
            target = status.get("target_floor")
            if target and target != self.current_floor:
                self._door = DoorState.MOVING
                self._moving_started = time.monotonic()
                self._pending_floor = target
                self._in_cabin = True
                self._publish_door_cmd("close")
                self.get_logger().info(
                    f"收到 MOVING_FLOOR → 車廂跨樓 {self.current_floor} → {target}"
                )

        # ---- 到達目標樓層後開門讓機器人駛出 ----
        elif self._robot_state == "EXITING_ELEVATOR":
            # 允許在 MOVING / CLOSED / OPENING 任一狀態接管
            # （納入 OPENING，避免機器人先於門全開就發出指令時卡住）
            if self._door in (DoorState.MOVING, DoorState.CLOSED, DoorState.OPENING):
                was_moving = self._door in (DoorState.MOVING, DoorState.CLOSED)
                self._door = DoorState.OPENING
                if was_moving:
                    self._door_progress = 0.0
                    self._publish_door_cmd("open")
                self._in_cabin = False
                self.get_logger().info(
                    f"收到 EXITING_ELEVATOR → 開門於 {self.current_floor}"
                )

        # ---- 巡檢完成點亮下一個可按按鈕 ----
        elif self._robot_state == "INSPECTING":
            self._in_cabin = False

    def _mark_inspection(self) -> None:
        """在巡檢狀態下記錄已完成的樓層。

        放在 ``_tick()`` 而非只在收到 ``/robot_status`` 時處理，
        以免因狀態訊息恰好發佈在轉換瞬間而漏記。
        """
        if self._robot_state != "INSPECTING":
            return
        self._in_cabin = False
        if self.current_floor not in self._inspected_floors:
            self._inspected_floors.append(self.current_floor)
            self.get_logger().info(
                f"巡檢完成：{self.current_floor}（累計 {self._inspected_floors}）"
            )

    # =================================================================
    # 模擬時鐘
    # =================================================================
    def _tick(self) -> None:
        """20 Hz 推進電梯狀態機並發佈感測器資料。"""
        now = time.monotonic()

        # ---- 待處理的呼叫指令延遲執行 ----
        if self._pending_cmd and self._pressed_at is not None:
            if now - self._pressed_at >= self.call_delay:
                self._open_doors("呼叫後送電梯至大廳")

        # ---- 門開啟動畫 ----
        if self._door == DoorState.OPENING:
            self._door_progress = min(1.0, self._door_progress + 0.05 / self.open_duration)
            if self._door_progress >= 1.0:
                self._door = DoorState.OPEN
                self.get_logger().info("電梯門已完全開啟")

        # ---- 門關閉動畫 ----
        elif self._door == DoorState.CLOSING:
            self._door_progress = max(0.0, self._door_progress - 0.05 / self.close_duration)
            if self._door_progress <= 0.0:
                self._door = DoorState.CLOSED
                self.get_logger().info("電梯門已完全關閉")

        # ---- 跨樓移動 ----
        elif self._door == DoorState.MOVING:
            elapsed = now - getattr(self, "_moving_started", now)
            if elapsed >= self.move_duration:
                self.current_floor = self._pending_floor or self.current_floor
                self._door = DoorState.OPENING
                self._door_progress = 0.0
                self._lit_button = None
                self._publish_door_cmd("open")
                self.get_logger().info(f"已抵達 {self.current_floor}，開門")

        # ---- 發佈狀態與偽感測器 ----
        self._mark_inspection()
        self._publish_state(now)
        if self._scan_pub is not None:
            self._publish_fake_scan(now)

    def _tick_camera(self) -> None:
        """偽相機獨立時鐘（2 Hz），避免拖慢主狀態機迴圈。"""
        if self._cam_pub is not None:
            self._publish_fake_camera(time.monotonic())

    # =================================================================
    # 感測器模擬
    # =================================================================
    def _front_distance(self) -> float:
        """依門狀態計算正前方淨空距離（門縫漸變）。"""
        closed = DOOR_CLOSED_DISTANCE_M
        opened = DOOR_OPEN_DISTANCE_M
        return closed + (opened - closed) * self._door_progress

    def _publish_fake_scan(self, now: float) -> None:
        """發佈偽 LiDAR：正前方淨空隨門開關改變。

        這讓 ``fsm_node`` 的 ``wait_for_door()``（取正前方中位數）
        能真實感知到「門開了」，達成 Headless 閉環。
        """
        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "laser_frame"

        msg.angle_min = -math.pi
        msg.angle_max = math.pi
        msg.angle_increment = 2 * math.pi / 360      # 360 束
        msg.time_increment = 0.0
        msg.scan_time = 0.05
        msg.range_min = 0.05
        msg.range_max = 12.0

        front = self._front_distance()
        ranges: list[float] = []
        for i in range(360):
            angle = -math.pi + i * msg.angle_increment
            # 正前方 ±20 度使用動態距離，其餘為走廊側牆
            if abs(math.sin(angle)) < math.sin(math.radians(20.0)):
                ranges.append(front)
            else:
                ranges.append(CABIN_DEPTH_M if self._in_cabin else CORRIDOR_SIDE_DISTANCE_M)

        msg.ranges = ranges
        msg.intensities = [0.0] * 360
        self._scan_pub.publish(msg)

    def _publish_fake_camera(self, now: float) -> None:
        """發佈偽電梯按鈕面板影像。

        被呼叫的樓層按鈕會「點亮」（高亮度），其餘為暗色，
        讓 OpenCV Template Matching 在無 Gazebo GUI 時也能運作。

        解析度可由 ``SIM_CAMERA_WIDTH`` / ``SIM_CAMERA_HEIGHT`` 調整（預設 640x360）。
        預設不採用 1920x1080：單幀 BGR 約 6MB，序列化開銷會拖慢
        rclpy 的單執行緒 executor，讓狀態機實際只有 ~1 Hz，
        電梯門開啟明顯滯後（實測 1.5m/s vs 預期 2.5m/s）。
        按鈕座標會依比例縮放，版面配置與 init-db 種子資料一致。
        """
        try:
            import numpy as np
        except ImportError:
            return

        width, height = self.cam_width, self.cam_height
        scale = width / 1920.0

        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:, :] = (28, 28, 32)                       # 面板底色（BGR）

        for idx, label in enumerate(PANEL_BUTTON_ORDER):
            bx = int((760 + idx * 70) * scale)
            by = int((420 if idx <= 3 else 490) * scale)
            bw = max(4, int(PANEL_BUTTON_W * scale))
            bh = max(4, int(PANEL_BUTTON_H * scale))
            lit = (label == self._lit_button)
            color = (90, 220, 120) if lit else (70, 70, 78)
            img[by:by + bh, bx:bx + bw] = color
            # 按鈕外框
            img[max(0, by - 1):by + bh + 1, max(0, bx - 1):bx + bw + 1] = (160, 160, 170)

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "camera_link"
        msg.height = height
        msg.width = width
        msg.encoding = "bgr8"
        msg.is_bigendian = 0
        msg.step = width * 3
        msg.data = img.tobytes()
        self._cam_pub.publish(msg)

    def _publish_state(self, now: float) -> None:
        """發佈電梯模擬狀態。"""
        self._state_pub.publish(String(data=json.dumps({
            "elevator_id": self.elevator_id,
            "door_state": self._door.value,
            "door_open_ratio": round(self._door_progress, 3),
            "front_distance_m": round(self._front_distance(), 3),
            "current_floor": self.current_floor,
            "pending_floor": getattr(self, "_pending_floor", None),
            "in_cabin": self._in_cabin,
            "robot_state": self._robot_state,
            "lit_button": self._lit_button,
            "inspected_floors": list(self._inspected_floors),
            "press_count": self._press_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)))

    def _publish_door_cmd(self, action: str) -> None:
        """發佈門板指令給 Gazebo 門板控制器（若啟用）。"""
        if not self.drive_gazebo_doors:
            return
        self._door_cmd_pub.publish(String(data=json.dumps({
            "action": action,
            "elevator_id": self.elevator_id,
            "target_ratio": 1.0 if action == "open" else 0.0,
            "door_center_width": DOOR_CENTER_WIDTH_M,
        })))

    # =================================================================
    # 內部動作
    # =================================================================
    def _open_doors(self, reason: str) -> None:
        """開啟電梯門。

        防禦：門若正在「關閉」或「跨樓移動」中則忽略開啟請求——
        真實電梯門在關閉途中不會因新的呼叫而重新打開，
        否則會造成門反覆開關、FSM 狀態機卡在 ENTERING_ELEVATOR。
        """
        if self._door in (
            DoorState.OPEN, DoorState.OPENING,
            DoorState.CLOSING, DoorState.MOVING,
        ):
            if self._door in (DoorState.CLOSING, DoorState.MOVING):
                self.get_logger().warn(
                    f"忽略開門請求（門正在 {self._door.value}）：{reason}"
                )
            return
        self._door = DoorState.OPENING
        self._door_progress = 0.0
        self._pending_cmd = None
        self._publish_door_cmd("open")
        self.get_logger().info(f"開啟電梯門（{reason}）")


def main(args: Optional[list[str]] = None) -> None:
    """程式進入點。"""
    rclpy.init(args=args)
    node = ElevatorSimNode()
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