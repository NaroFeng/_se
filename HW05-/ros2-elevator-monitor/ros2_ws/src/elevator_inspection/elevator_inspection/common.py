"""跨樓層巡檢系統共用設定與常數。

集中定義 ROS 2 topic 名稱、錯誤碼與預設參數，
讓 fsm_node / button_recognizer / bridge_rest_node 三個節點保持一致。
"""

from __future__ import annotations

import os
from enum import Enum

# --------------------------------------------------------------------
# ROS 2 Topic 定義
# --------------------------------------------------------------------
# Web -> ROS 2（bridge_rest_node 發佈，fsm_node 訂閱）
TOPIC_COMMAND = "/inspection/command"

# ROS 2 -> Web（fsm_node 發佈，bridge_rest_node 訂閱）
TOPIC_ROBOT_STATUS = "/robot_status"
TOPIC_EVENT_LOG = "/inspection/event_log"

# fsm_node -> button_recognizer（要求確認某顆按鈕）
TOPIC_BUTTON_REQUEST = "/elevator/button/request"
# button_recognizer -> fsm_node（回報視覺／觸覺確認結果）
TOPIC_BUTTON_RESULT = "/elevator/button/result"
# button_recognizer -> 儀表板（視覺階段即時結果）
TOPIC_VISION_RESULT = "/elevator/vision_result"

# 硬體抽象層（WP 0）：推桿與 MCU 橋接
TOPIC_ACTUATOR_CMD = "/actuator/cmd"        # button_recognizer -> MCU
TOPIC_ACTUATOR_STATUS = "/actuator/status"  # MCU -> button_recognizer

# 硬體抽象層（WP 0）：麥克納姆輪底盤
TOPIC_CMD_VEL = "/cmd_vel"                  # fsm_node -> 底盤（geometry_msgs/Twist）
TOPIC_SCAN = "/scan"                        # LiDAR -> fsm_node（判斷電梯門）

# Digital Twin：電梯模擬環境
TOPIC_ELEVATOR_STATE = "/elevator/sim_state"    # elevator_sim_node -> fsm_node
TOPIC_DOOR_CMD = "/elevator/door_cmd"           # elevator_sim_node -> Gazebo 門板

# 感測器 topic（模擬器／實體機器人提供）
TOPIC_DOOR_SENSOR = "/elevator/door_sensor"
TOPIC_IN_CABIN = "/elevator/in_cabin"
TOPIC_FLOOR_REACHED = "/elevator/floor_reached"
TOPIC_BATTERY = "/robot/battery"
TOPIC_IMAGE = "/camera/color/image_raw"

# --------------------------------------------------------------------
# 支援的控制指令（需與 bridge_rest_node.ALLOWED_COMMANDS 對應）
# --------------------------------------------------------------------
ALLOWED_COMMANDS = {
    "start_inspection",
    "goto_floor",
    "stop_inspection",
    "pause",
    "resume",
    "switch_map",
    "call_elevator",
    "press_button",
    "reset_fsm",
}

# --------------------------------------------------------------------
# 錯誤碼
# --------------------------------------------------------------------
class ErrorCode:
    """回報給 Web 前端的錯誤碼（對應 README 的監控顯示）。"""

    NONE = 0
    BUTTON_NOT_FOUND = 1001          # 影像中找不到目標按鈕
    LOW_CONFIDENCE = 1002            # 相似度低於門檻
    TACTILE_FAILED = 1003            # 力感測器未偵測到按壓
    DOOR_TIMEOUT = 1004              # 等待電梯開門逾時
    CABIN_DETECT_FAILED = 1005       # 未偵測到進入車廂
    FLOOR_MISMATCH = 1006            # 抵達樓層與目標不符
    NAV_FAILED = 1007                # 導航失敗
    MAP_SWITCH_FAILED = 1008         # 地圖切換失敗
    TIMEOUT = 1009                   # 步驟逾時

    MESSAGES = {
        NONE: "無錯誤",
        BUTTON_NOT_FOUND: "影像中找不到目標按鈕",
        LOW_CONFIDENCE: "按鈕相似度低於門檻",
        TACTILE_FAILED: "力感測器未偵測到按壓動作",
        DOOR_TIMEOUT: "等待電梯開門逾時",
        CABIN_DETECT_FAILED: "未偵測到進入電梯車廂",
        FLOOR_MISMATCH: "抵達樓層與目標不符",
        NAV_FAILED: "導航至目標點失敗",
        MAP_SWITCH_FAILED: "地圖切換失敗",
        TIMEOUT: "步驟執行逾時",
    }

    @classmethod
    def describe(cls, code: int) -> str:
        return cls.MESSAGES.get(code, f"未知錯誤碼 {code}")


# --------------------------------------------------------------------
# 巡檢事件類型（需與 PostgreSQL inspection_logs.event_type 的 CHECK 一致）
# --------------------------------------------------------------------
class EventType:
    TASK_START = "task_start"
    TASK_FINISH = "task_finish"
    FSM_TRANSITION = "fsm_transition"
    NAV_RESULT = "nav_result"
    ELEVATOR_CALL = "elevator_call"
    ELEVATOR_ENTER = "elevator_enter"
    ELEVATOR_EXIT = "elevator_exit"
    BUTTON_DETECT = "button_detect"
    BUTTON_PRESS = "button_press"
    MAP_SWITCH = "map_switch"
    INFO = "info"
    ERROR = "error"


# --------------------------------------------------------------------
# 環境變數
# --------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class Config:
    """節點預設參數（皆可用環境變數覆寫）。"""

    # 機器人識別碼：中央大腦據此區分不同測試機台／實機的學習來源
    # 範例：amr-proto-01（測試機台 A）、amr-proto-02（測試機台 B）
    ROBOT_NAME = os.getenv("ROBOT_NAME", "amr-proto-01")

    # 巡檢樓層順序（由低到高）
    DEFAULT_WAYPOINTS = ["B2", "B1", "1F", "2F", "3F", "4F", "5F"]
    DEFAULT_START_FLOOR = os.getenv("DEFAULT_FLOOR", "1F")

    # 每個狀態的最長執行時間（秒），逾時則轉入 ERROR
    TIMEOUT_IDLE = 3600.0
    TIMEOUT_NAVIGATION = _env_float("FSM_NAV_TIMEOUT", 60.0)
    TIMEOUT_ELEVATOR_WAIT = _env_float("FSM_ELEVATOR_TIMEOUT", 45.0)
    TIMEOUT_ENTER = _env_float("FSM_ENTER_TIMEOUT", 30.0)
    TIMEOUT_RIDE = _env_float("FSM_RIDE_TIMEOUT", 120.0)
    TIMEOUT_EXIT = _env_float("FSM_EXIT_TIMEOUT", 30.0)
    TIMEOUT_BUTTON = _env_float("FSM_BUTTON_TIMEOUT", 20.0)
    TIMEOUT_INSPECT = _env_float("FSM_INSPECT_TIMEOUT", 300.0)

    # 狀態發佈頻率（Hz）
    STATUS_PUBLISH_HZ = _env_float("FSM_STATUS_HZ", 5.0)

    # 按鈕辨識相關
    VISION_CONFIDENCE_THRESHOLD = _env_float("VISION_THRESHOLD", 0.75)
    PRESS_DURATION_MS = _env_int("PRESS_DURATION_MS", 1200)

    # 模擬參數：讓 demo 模式下流程可自動推進
    SIMULATION_MODE = os.getenv("SIMULATION_MODE", "true").lower() == "true"
    SIM_ELEVATOR_WAIT_SEC = _env_float("SIM_ELEVATOR_WAIT_SEC", 3.0)
    SIM_RIDE_SEC = _env_float("SIM_RIDE_SEC", 4.0)
    SIM_NAV_SEC = _env_float("SIM_NAV_SEC", 2.0)      # 移動至電梯廳
    SIM_ENTER_SEC = _env_float("SIM_ENTER_SEC", 2.5)  # 駛入車廂
    SIM_EXIT_SEC = _env_float("SIM_EXIT_SEC", 2.5)    # 駛出電梯

    # 硬體抽象層（WP 0）
    HARDWARE_MODE = os.getenv("HARDWARE_MODE", "mock")   # mock | hybrid | real
    CAMERA_DEVICE = os.getenv("CAMERA_DEVICE", "/dev/video0")
    CAMERA_INDEX = _env_int("CAMERA_INDEX", 0)
    SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
    SERIAL_BAUD = _env_int("SERIAL_BAUD", 115200)
    BUTTON_TEMPLATE_DIR = os.getenv("BUTTON_TEMPLATE_DIR", "/maps/buttons")

    # 底盤參數（麥克納姆輪）
    MAX_LINEAR_Y = _env_float("MAX_LINEAR_Y", 0.15)      # 橫移速度上限 (m/s)
    PIXEL_TO_METER = _env_float("PIXEL_TO_METER", 0.0005)  # 像素→公尺換算
    DOOR_WAIT_SEC = _env_float("DOOR_WAIT_SEC", 30.0)    # 等待電梯開門逾時