#!/usr/bin/env python3
"""button_recognizer：電梯按鈕視覺／觸覺雙重確認節點。

職責
----
1. **視覺確認（Vision）**
   模擬（或實際執行）Template Matching / YOLO 比對，判斷影像中的按鈕
   是否為指定的目標樓層按鈕，並輸出相似度（confidence）。

2. **觸覺確認（Tactile）**
   模擬按壓機械臂動作，由力感測器／行程開關回報是否確實觸發按鈕。

3. **雙重確認**
   視覺與觸覺**都通過**才回傳 ``confirmed=True``，
   任一環節失敗都會帶回對應的 ``error_code`` 供 FSM 決定復原策略。

Topic 介面
----------
訂閱 ``/elevator/button/request``
    JSON: ``{"request_id", "floor_code", "button_label", "target_floor",
             "confidence_threshold", "press_duration_ms"}``

發佈 ``/elevator/button/result``
    JSON: ``{"request_id", "floor_code", "button_label", "confirmed",
             "vision": {...}, "tactile": {...}, "elapsed_ms", "error_code"}``

發佈 ``/elevator/vision_result``
    僅視覺階段結果，供儀表板即時顯示比對信心度。

模擬策略
--------
``SIMULATION_MODE=true``（預設）時不需實際相機與力感測器，
由本節點依 floor_code 產生可重現的信心度，並模擬力感測器回應。
設定為 ``false`` 時才會嘗試使用 OpenCV 讀取真實影像。
"""

from __future__ import annotations

import json
import random
import time
import zlib
from datetime import datetime, timezone
from typing import Any, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .common import (
    TOPIC_ACTUATOR_CMD,
    TOPIC_ACTUATOR_STATUS,
    TOPIC_BUTTON_REQUEST,
    TOPIC_BUTTON_RESULT,
    TOPIC_IMAGE,
    TOPIC_VISION_RESULT,
    Config,
    ErrorCode,
)
from .hardware_hal import get_hal

try:  # OpenCV 為選用依賴，模擬模式下不需要
    import cv2
    import numpy as np

    HAS_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None
    np = None
    HAS_CV2 = False


class ButtonRecognizer(Node):
    """電梯按鈕視覺／觸覺雙重確認節點。"""

    def __init__(self) -> None:
        super().__init__("button_recognizer")

        # 硬體抽象層：視覺與觸覺的底層實作集中於此，
        # 本節點只呼叫 HAL 介面，不直接觸碰 OpenCV / Serial。
        self._hal = get_hal()
        self._sim_mode = Config.SIMULATION_MODE

        # 訂閱按鈕確認請求
        self.create_subscription(String, TOPIC_BUTTON_REQUEST, self._on_request, 10)

        # 發佈確認結果給 fsm_node
        self._result_pub = self.create_publisher(String, TOPIC_BUTTON_RESULT, 10)
        # 發佈視覺階段結果給儀表板
        self._vision_pub = self.create_publisher(String, TOPIC_VISION_RESULT, 10)

        # 推桿綁定 ROS 2 Topic /actuator/cmd（real 模式由外部 MCU 橋接節點回應）
        self._actuator_status_pub = self.create_publisher(
            String, TOPIC_ACTUATOR_CMD, 10
        )
        self.create_subscription(String, TOPIC_ACTUATOR_STATUS, self._on_actuator_status, 10)
        self._hal.actuator.set_ros_bridge(
            publish_cmd=lambda data: self._actuator_status_pub.publish(
                String(data=json.dumps(data, ensure_ascii=False))
            ),
            status_callback=lambda cb: cb(self._on_actuator_status),
        )

        # 已完成的確認紀錄（供查詢）
        self._history: list[dict[str, Any]] = []

        hw = self._hal.describe()
        self.get_logger().info(
            f"button_recognizer 啟動（HARDWARE_MODE={hw['hardware_mode']}, "
            f"相機={'real' if self._hal.camera.is_real else 'mock'}, "
            f"推桿={'real' if self._hal.actuator.is_real else 'mock'}, "
            f"門檻={Config.VISION_CONFIDENCE_THRESHOLD}）"
        )

    def _on_actuator_status(self, msg: Any) -> None:
        """接收 MCU 回傳的推桿狀態（real 模式）。"""
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError):
            return
        self._hal.actuator._on_ros_status(data)

    # =================================================================
    # ROS 回呼
    # =================================================================
    def _on_image(self, msg: Any) -> None:  # pragma: no cover - 需真實相機
        """真實模式：快取最新影像，供視覺比對使用。"""
        self._latest_image = msg

    def _on_request(self, msg: String) -> None:
        """處理來自 fsm_node 的按鈕確認請求。"""
        try:
            req = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("無法解析按鈕請求 JSON")
            return

        request_id = req.get("request_id", "")
        floor_code = req.get("floor_code", "?")
        button_label = req.get("button_label", floor_code)
        target_floor = req.get("target_floor", floor_code)
        threshold = float(req.get("confidence_threshold", Config.VISION_CONFIDENCE_THRESHOLD))
        press_ms = int(req.get("press_duration_ms", Config.PRESS_DURATION_MS))
        attempt = int(req.get("attempt", 0))

        self.get_logger().info(
            f"收到按鈕確認請求 {request_id}: 樓層={floor_code} 按鈕={button_label} "
            f"門檻={threshold} 重試={attempt}"
        )

        started = time.monotonic()
        # 參數來源（central_brain = 由中央大腦學習後提供，local_default = 本地預設）
        policy_source = req.get("policy_source", "local_default")

        # ---------- 階段一：視覺確認 ----------
        vision = self._visual_confirmation(
            floor_code, button_label, target_floor, threshold, attempt
        )
        self._publish_vision(request_id, floor_code, button_label, vision)

        if not vision["detected"] or not vision["passed"]:
            self._send_result(
                request_id, floor_code, button_label, target_floor,
                confirmed=False, vision=vision, tactile=None,
                elapsed_ms=self._elapsed_ms(started),
                error_code=ErrorCode.BUTTON_NOT_FOUND if not vision["detected"]
                else ErrorCode.LOW_CONFIDENCE,
                policy_source=policy_source,
            )
            return

        # ---------- 階段二：觸覺確認 ----------
        tactile = self._tactile_confirmation(press_ms)

        if not tactile["confirmed"]:
            self._send_result(
                request_id, floor_code, button_label, target_floor,
                confirmed=False, vision=vision, tactile=tactile,
                elapsed_ms=self._elapsed_ms(started),
                error_code=ErrorCode.TACTILE_FAILED,
                policy_source=policy_source,
            )
            return

        # ---------- 雙重確認通過 ----------
        self._send_result(
            request_id, floor_code, button_label, target_floor,
            confirmed=True, vision=vision, tactile=tactile,
            elapsed_ms=self._elapsed_ms(started),
            error_code=ErrorCode.NONE,
            policy_source=policy_source,
        )

    # =================================================================
    # 視覺確認
    # =================================================================
    def _visual_confirmation(
        self, floor_code: str, button_label: str, target_floor: str, threshold: float,
        attempt: int = 0,
    ) -> dict[str, Any]:
        """判斷影像中的按鈕是否為目標樓層按鈕。

        底層實作委派給硬體抽象層（HAL）的 CameraInterface：
        * ``mock``  → zlib.crc32 確定性模擬分數
        * ``real``  → cv2.VideoCapture + cv2.matchTemplate，並回傳偏移量
        """
        vision = self._hal.camera.match_button(
            button_label=button_label,
            threshold=threshold,
            floor_code=floor_code,
            attempt=attempt,
        )

        passed = vision.confidence >= threshold
        return {
            "detected": vision.detected,
            "confidence": vision.confidence,
            "threshold": threshold,
            "passed": passed,
            "method": vision.method,
            "attempt": attempt,
            "button_label": button_label,
            "target_floor": target_floor,
            "bbox": vision.bbox,
            # 水平偏移量：麥克納姆輪底盤據此以 linear.y 左右橫移對準按鈕
            "offset_x_px": vision.offset_x_px,
            "offset_y_px": vision.offset_y_px,
            "hardware_mode": self._hal.mode,
            "camera_ready": self._hal.camera.is_real,
        }

    def _simulate_vision_score(
        self, floor_code: str, button_label: str, attempt: int = 0
    ) -> tuple[float, str]:
        """模擬視覺比對信心度。

        以 floor_code + button_label 作為亂數種子，讓同一組按鈕每次都得到
        相同結果（可重現），且大多落在門檻之上；偶發低於門檻以模擬反光情境。

        注意：不可使用內建 hash()，因為 Python 預設會隨機化雜湊種子
        （PYTHONHASHSEED），會導致每次啟動的分數都不同。使用 zlib.crc32
        取得跨行程穩定的雜湊值。
        """
        seed = zlib.crc32(f"{floor_code}|{button_label}".encode("utf-8"))
        rng = random.Random(seed + attempt * 7919)

        threshold = Config.VISION_CONFIDENCE_THRESHOLD
        # 每次重試時提高成功機率，模擬機器人調整姿態後重新拍攝
        fail_probability = max(0.03, 0.30 - attempt * 0.08)

        if rng.random() < fail_probability:
            # 模擬反光／陰影造成的低信心度（略低於門檻，觸發復原流程）
            score = rng.uniform(0.45, max(0.5, threshold - 0.05))
        elif rng.random() < 0.85:
            # 正常良好比對
            score = rng.uniform(threshold + 0.08, 0.99)
        else:
            # 接近門檻
            score = rng.uniform(threshold, threshold + 0.10)

        return round(score, 4), "simulated_template_matching"

    def _template_match(self, image_msg: Any, button_label: str) -> float:  # pragma: no cover
        """真實影像的 Template Matching（簡化實作）。"""
        if cv2 is None or np is None:
            return 0.0
        try:
            msg = image_msg
            height = int(msg.height)
            width = int(msg.width)
            # 將 sensor_msgs/Image 轉為 numpy 影像（假設 rgb8）
            data = np.frombuffer(bytes(msg.data), dtype=np.uint8)
            frame = data.reshape((height, width, -1))[:, :, :3]
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

            template = self._load_template(button_label)
            if template is None:
                return 0.0

            result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            return float(max_val)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f"Template Matching 失敗：{exc}")
            return 0.0

    def _load_template(self, button_label: str) -> Optional[Any]:  # pragma: no cover
        """載入按鈕模板圖（實體機器人部署時替換此路徑）。"""
        import os

        path = os.getenv("BUTTON_TEMPLATE_DIR", "/maps/buttons") + f"/E1_{button_label}.png"
        if cv2 is not None and os.path.isfile(path):
            template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            return template
        return None

    @staticmethod
    def _estimate_bbox(button_label: str) -> dict[str, int]:
        """依按鈕面板版面配置（與 init-db 種子資料一致）推算外框。"""
        order = ["B2", "B1", "1F", "2F", "3F", "4F", "5F"]
        idx = order.index(button_label) if button_label in order else 0
        return {
            "x": 760 + idx * 70,
            "y": 420 if idx <= 3 else 490,
            "width": 64,
            "height": 64,
        }

    # =================================================================
    # 觸覺確認（委派給硬體抽象層）
    # =================================================================
    def _tactile_confirmation(self, press_duration_ms: int) -> dict[str, Any]:
        """按壓按鈕並由力感測器／微動開關驗證。

        底層實作委派給硬體抽象層（HAL）的 ActuatorInterface：
        * ``mock`` → 模擬按壓與力感測器回應
        * ``real`` → Serial 送 JSON 指令給 MCU，等待微動開關回傳 tactile_ok
        """
        return self._hal.actuator.press(press_duration_ms).to_dict()

    # =================================================================
    # 發佈
    # =================================================================
    def _publish_vision(
        self, request_id: str, floor_code: str, button_label: str, vision: dict[str, Any]
    ) -> None:
        """發佈視覺階段結果（供儀表板即時顯示）。"""
        payload = {
            "request_id": request_id,
            "floor_code": floor_code,
            "button_label": button_label,
            "confidence": vision["confidence"],
            "threshold": vision["threshold"],
            "passed": vision["passed"],
            "method": vision["method"],
            "attempt": vision.get("attempt", 0),
            "bbox": vision["bbox"],
            # 水平偏移量：麥克納姆輪底盤據此以 linear.y 左右橫移對準按鈕
            "offset_x_px": vision.get("offset_x_px", 0),
            "offset_y_px": vision.get("offset_y_px", 0),
            "hardware_mode": vision.get("hardware_mode", "mock"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._vision_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))
        self.get_logger().info(
            f"[視覺] {button_label} 相似度={vision['confidence']} "
            f"門檻={vision['threshold']} 結果={'通過' if vision['passed'] else '不通過'}"
        )

    def _send_result(
        self,
        request_id: str,
        floor_code: str,
        button_label: str,
        target_floor: str,
        confirmed: bool,
        vision: dict[str, Any],
        tactile: Optional[dict[str, Any]],
        elapsed_ms: float,
        error_code: int,
        policy_source: str = "local_default",
    ) -> None:
        """發佈完整確認結果給 fsm_node。"""
        payload = {
            "request_id": request_id,
            "floor_code": floor_code,
            "button_label": button_label,
            "target_floor": target_floor,
            "confirmed": confirmed,
            "vision": vision,
            "tactile": tactile,
            # 學習訊號：本次使用的門檻與重試次數
            "attempt": vision.get("attempt", 0),
            "policy_source": policy_source,
            "elapsed_ms": elapsed_ms,
            "error_code": error_code,
            "error_message": ErrorCode.describe(error_code),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._result_pub.publish(String(data=json.dumps(payload, ensure_ascii=False)))

        # 保留最近 20 筆供除錯
        self._history.append(payload)
        del self._history[:-20]

        level = self.get_logger().info if confirmed else self.get_logger().warning
        level(
            f"[{'確認成功' if confirmed else '確認失敗'}] {button_label} "
            f"{ErrorCode.describe(error_code)} ({elapsed_ms:.0f}ms)"
        )

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.monotonic() - started) * 1000.0


def main(args: Optional[list[str]] = None) -> None:
    """程式進入點。"""
    rclpy.init(args=args)
    node = ButtonRecognizer()
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