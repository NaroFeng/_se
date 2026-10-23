"""與 ROS 2 端 `elevator_inspection/common.py` 保持一致的事件類型常數。

集中定義避免後端與 ROS 2 兩側各寫一份而產生落差。
"""

from __future__ import annotations


class EventType:
    """巡檢事件類型（對應 PostgreSQL inspection_logs.event_type 的 CHECK 約束）。"""

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

    #: 會觸發中央大腦按鈕參數學習的事件
    BUTTON_EVENTS = frozenset({BUTTON_DETECT, BUTTON_PRESS})