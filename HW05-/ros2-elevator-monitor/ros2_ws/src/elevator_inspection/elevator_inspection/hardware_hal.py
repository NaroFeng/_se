"""硬體抽象層（Hardware Abstraction Layer, HAL）。

目的
----
讓 `fsm_node.py`（跨樓層巡檢狀態機）與 `button_recognizer.py`（按鈕辨識）
**完全不需要修改**，即可在模擬環境與實體硬體之間切換。

三個介面
--------
* :class:`CameraInterface`      — USB 視訊鏡頭（Logitech, ``/dev/video0``）
* :class:`ActuatorInterface`    — 線性推桿 + 彈簧微動開關（MCU, ``/dev/ttyUSB0``）
* :class:`MecanumBaseInterface` — 麥克納姆輪底盤 + 電梯門感測

硬體對應（WP 0 定案）
--------------------
============  ==========================================================
底盤          IKEA 推車改裝麥克納姆輪，支援 ``linear.y`` 左右橫移微調
視覺          USB 羅技視訊鏡頭，Eye-in-Hand 掛載於推桿旁
按壓／觸覺    線性推桿 + 彈簧微動開關，由 MCU 控制並回傳 ``tactile_ok``
車載電腦      樹莓派（ARM64）或迷你電腦（AMD64）單獨執行 ros2-bridge
============  ==========================================================

三種模式（由 ``HARDWARE_MODE`` 環境變數決定）
------------------------------------------
``mock``（預設）
    完全模擬。不需任何硬體，適合 CI 與開發。
``hybrid``
    相機用真實影像（OpenCV），推桿與底盤仍為模擬。
    適合在辦公室先驗證視覺管線。
``real``
    全部使用真實硬體。

降級策略
--------
若 ``real`` 模式但硬體不可用（裝置不存在、OpenCV 未安裝），
HAL 會**自動降級為 mock**並記錄警告，確保機器人仍可安全執行，
不會因為硬體臨時故障而整個巡檢系統停擺。
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("hardware_hal")

# --------------------------------------------------------------------
# OpenCV 為選用依賴：mock 模式不需要，real 模式才需要
# --------------------------------------------------------------------
try:
    import cv2
    import numpy as np

    HAS_CV2 = True
except ImportError:  # pragma: no cover
    cv2 = None
    np = None
    HAS_CV2 = False


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# =====================================================================
# 模式
# =====================================================================
class HardwareMode:
    """HARDWARE_MODE 環境變數的合法值。"""

    MOCK = "mock"
    HYBRID = "hybrid"
    REAL = "real"
    GAZEBO = "gazebo"        # Digital Twin：Gazebo 仿真環境

    ALL = (MOCK, HYBRID, REAL, GAZEBO)


def get_hardware_mode() -> str:
    """讀取並正規化 HARDWARE_MODE（預設 mock）。"""
    mode = _env_str("HARDWARE_MODE", HardwareMode.MOCK).strip().lower()
    if mode not in HardwareMode.ALL:
        logger.warning(
            f"HARDWARE_MODE={mode!r} 不合法，可選 {HardwareMode.ALL}；已退回 mock"
        )
        return HardwareMode.MOCK
    return mode


def is_real_camera() -> bool:
    """相機是否應使用真實影像（real / hybrid / gazebo 都使用）。"""
    return get_hardware_mode() in (
        HardwareMode.REAL, HardwareMode.HYBRID, HardwareMode.GAZEBO,
    )


def uses_physical_base() -> bool:
    """底盤是否由 Gazebo / 實體的 /cmd_vel 驅動。"""
    return get_hardware_mode() in (HardwareMode.REAL, HardwareMode.GAZEBO)


# =====================================================================
# 共用資料結構
# =====================================================================
@dataclass
class VisionResult:
    """視覺比對結果。

    Attributes
    ----------
    confidence: 相似度（0~1）
    offset_x_px: 按鈕在影像中的水平偏移量，供麥克納姆輪以 ``linear.y`` 微調對準
    offset_y_px: 垂直偏移量（預留）
    bbox: 按鈕外框 {x, y, width, height}
    method: 比對方法（template_matching / simulated）
    """

    confidence: float
    detected: bool = True
    offset_x_px: int = 0
    offset_y_px: int = 0
    bbox: dict[str, int] = field(default_factory=dict)
    method: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 4),
            "detected": self.detected,
            "offset_x_px": self.offset_x_px,
            "offset_y_px": self.offset_y_px,
            "bbox": self.bbox,
            "method": self.method,
        }


@dataclass
class TactileResult:
    """觸覺回饋結果。"""

    confirmed: bool
    press_duration_ms: int
    force_kg: float = 0.0
    sensor: str = "none"
    threshold_kg: float = 2.5
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmed": self.confirmed,
            "press_duration_ms": self.press_duration_ms,
            "force_kg": self.force_kg,
            "sensor": self.sensor,
            "threshold_kg": self.threshold_kg,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


@dataclass
class BaseStatus:
    """麥克納姆輪底盤狀態。"""

    floor_reached: bool = False
    door_open: bool = False
    in_cabin: bool = False
    aligned: bool = False          # 是否已對準按鈕
    battery_percent: float = 100.0
    pose: dict[str, float] = field(
        default_factory=lambda: {"x": 1.0, "y": -1.0, "yaw": 0.0}
    )


# =====================================================================
# 1. CameraInterface — USB 視訊鏡頭
# =====================================================================
class CameraInterface:
    """視覺介面。

    ``mock``
        以 ``zlib.crc32`` 產生**跨行程確定性**的相似度（同一組按鈕結果可重現）。
    ``real``
        ``cv2.VideoCapture(CAMERA_INDEX)`` 擷取羅技鏡頭影像，
        以 ``cv2.matchTemplate`` 比對按鈕模板，並回傳偏移量供底盤微調。
    """

    #: 電梯廳面板版面（與 init-db 種子資料一致）
    BUTTON_ORDER = ["B2", "B1", "1F", "2F", "3F", "4F", "5F"]

    def __init__(self, mode: Optional[str] = None) -> None:
        self.mode = mode or get_hardware_mode()
        self.device = _env_str("CAMERA_DEVICE", "/dev/video0")
        self.camera_index = _env_int("CAMERA_INDEX", 0)
        self.frame_width = _env_int("CAMERA_WIDTH", 1920)
        self.frame_height = _env_int("CAMERA_HEIGHT", 1080)
        self.template_dir = _env_str("BUTTON_TEMPLATE_DIR", "/maps/buttons")
        self._templates: dict[str, Any] = {}
        self._cap = None
        self._last_frame = None
        self._degraded = False

        if self.mode == HardwareMode.REAL or self.mode == HardwareMode.HYBRID:
            if not HAS_CV2:
                logger.warning("HARDWARE_MODE=%s 但 OpenCV 未安裝，相機自動降級為 mock", self.mode)
                self._degraded = True
            else:
                self._open_camera()

    # ---------------- 資源管理 ----------------
    def _open_camera(self) -> None:
        """開啟視訊鏡頭。"""
        try:
            index = self.camera_index
            if self.device and self.device != f"/dev/video{index}":
                logger.info("嘗試以裝置路徑開啟相機：%s", self.device)

            self._cap = cv2.VideoCapture(index)
            if not self._cap.isOpened():
                raise RuntimeError(f"無法開啟相機 index={index} device={self.device}")

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            logger.info(
                "相機就緒：index=%s device=%s %dx%d",
                index, self.device, self.frame_width, self.frame_height,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("相機開啟失敗（%s），自動降級為 mock 模式", exc)
            self._degraded = True
            self._cap = None

    def close(self) -> None:
        """釋放相機資源。"""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None

    @property
    def is_real(self) -> bool:
        """目前是否真的在使用相機。"""
        return self._cap is not None and not self._degraded

    # ---------------- 模板 ----------------
    def _load_template(self, button_label: str) -> Optional[Any]:
        """載入按鈕模板圖（快取）。"""
        if button_label in self._templates:
            return self._templates[button_label]

        template = None
        if HAS_CV2:
            path = os.path.join(self.template_dir, f"E1_{button_label}.png")
            if os.path.isfile(path):
                template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)

        self._templates[button_label] = template
        if template is None:
            logger.debug("找不到按鈕模板：%s（改用版面推估外框）", button_label)
        return template

    def estimate_bbox(self, button_label: str) -> dict[str, int]:
        """依面板版面配置推算按鈕外框。"""
        order = self.BUTTON_ORDER
        idx = order.index(button_label) if button_label in order else 0
        return {
            "x": 760 + idx * 70,
            "y": 420 if idx <= 3 else 490,
            "width": 64,
            "height": 64,
        }

    # ---------------- 影像擷取 ----------------
    def capture(self) -> Optional[Any]:
        """擷取一幀影像（real 模式）。"""
        if not self.is_real:
            return None
        ok, frame = self._cap.read()
        if not ok:
            logger.warning("相機擷取影格失敗")
            return None
        self._last_frame = frame
        return frame

    # ---------------- 核心：比對 ----------------
    def match_button(
        self,
        button_label: str,
        threshold: float,
        floor_code: str = "",
        attempt: int = 0,
    ) -> VisionResult:
        """比對影像中的目標按鈕。

        Parameters
        ----------
        button_label: 目標按鈕文字（如 ``5F``）
        threshold: 判定門檻（由中央大腦提供）
        floor_code: 樓層代號（mock 模式作為亂數種子的一環）
        attempt: 重試次數（mock 模式用來模擬調整姿態後成功率提升）

        Returns
        -------
        VisionResult 含 confidence 與 offset_x_px（供麥克納姆輪橫移微調）
        """
        if self.is_real:
            result = self._match_real(button_label, threshold)
            if result is not None:
                return result
            logger.warning("real 模式比對失敗（可能無模板），退回模擬")

        return self._match_mock(floor_code, button_label, threshold, attempt)

    # ---------------- real：OpenCV Template Matching ----------------
    def _match_real(
        self, button_label: str, threshold: float
    ) -> Optional[VisionResult]:  # pragma: no cover - 需真實相機
        """真實影像的 Template Matching。"""
        template = self._load_template(button_label)
        if template is None:
            return None

        frame = self.capture()
        if frame is None:
            return None

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
            logger.warning("模板尺寸大於影像，無法比對")
            return None

        result = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        bbox = self.estimate_bbox(button_label)
        # 偏移量 = 實際位置 - 預期位置，供底盤左右橫移對準
        offset_x = int(max_loc[0] - bbox["x"])
        offset_y = int(max_loc[1] - bbox["y"])

        return VisionResult(
            confidence=float(max_val),
            detected=float(max_val) >= threshold,
            offset_x_px=offset_x,
            offset_y_px=offset_y,
            bbox={**bbox, "x": int(max_loc[0]), "y": int(max_loc[1])},
            method="template_matching",
        )

    # ---------------- mock：確定性模擬 ----------------
    def _match_mock(
        self, floor_code: str, button_label: str, threshold: float, attempt: int
    ) -> VisionResult:
        """模擬視覺比對。

        以 ``zlib.crc32``（而非內建 ``hash()``）作為亂數種子，
        確保跨行程確定性；``attempt`` 讓重試時重新取樣，
        模擬機器人調整姿態後成功率提升。
        """
        seed = zlib.crc32(f"{floor_code}|{button_label}".encode("utf-8"))
        rng = random.Random(seed + attempt * 7919)

        # 每次重試時失敗率遞減，模擬姿態調整後改善
        fail_probability = max(0.03, 0.30 - attempt * 0.08)

        if rng.random() < fail_probability:
            # 模擬反光／陰影造成的低信心度
            confidence = rng.uniform(0.45, max(0.5, threshold - 0.05))
        elif rng.random() < 0.85:
            # 正常良好比對
            confidence = rng.uniform(threshold + 0.08, 0.99)
        else:
            # 接近門檻
            confidence = rng.uniform(threshold, threshold + 0.10)

        # 模擬 ±12px 的水平偏移量（供 demo 顯示橫移微調）
        offset_x = rng.randint(-12, 12)

        return VisionResult(
            confidence=round(confidence, 4),
            detected=confidence >= threshold,
            offset_x_px=offset_x,
            offset_y_px=rng.randint(-6, 6),
            bbox=self.estimate_bbox(button_label),
            method="simulated_template_matching",
        )


# =====================================================================
# 2. ActuatorInterface — 線性推桿 + 彈簧微動開關
# =====================================================================
class ActuatorInterface:
    """按壓與觸覺介面。

    ``mock``
        模擬按壓並回傳成功（3% 機率失敗以測試復原流程）。
    ``real``
        透過 Serial（``/dev/ttyUSB0`` 或 ``/dev/ttyACM0``）送出 JSON 指令::

            {"cmd": "press", "duration_ms": 1200}

        並等待 MCU 回傳微動開關觸發結果::

            {"tactile_ok": true, "actual_ms": 1180}

        亦支援透過 ROS 2 Topic ``/actuator/cmd`` 與 ``/actuator/status``
        與 MCU 橋接節點通訊（由外部注入 publisher / subscription callback）。
    """

    def __init__(self, mode: Optional[str] = None) -> None:
        self.mode = mode or get_hardware_mode()
        self.serial_port = _env_str("SERIAL_PORT", "/dev/ttyUSB0")
        self.serial_baud = _env_int("SERIAL_BAUD", 115200)
        self.force_threshold_kg = float(_env_str("FORCE_THRESHOLD_KG", "2.5"))
        self.command_timeout_sec = float(_env_str("ACTUATOR_TIMEOUT_SEC", "3.0"))
        self._serial = None
        self._degraded = False
        self._rng = random.Random()

        # ROS 2 通訊回呼（由呼叫端注入，避免在此依賴 rclpy）
        self._publish_cmd = None            # Callable[[dict], None]
        self._latest_status: dict[str, Any] = {}

        if self.mode == HardwareMode.REAL:
            self._open_serial()

    # ---------------- 資源管理 ----------------
    def _open_serial(self) -> None:
        """開啟序列埠連線 MCU。"""
        try:
            import serial  # type: ignore[import-not-found]

            self._serial = serial.Serial(
                self.serial_port, self.serial_baud, timeout=self.command_timeout_sec
            )
            logger.info(
                "推桿 MCU 已連線：%s @ %d baud", self.serial_port, self.serial_baud
            )
        except ImportError:
            logger.warning(
                "pyserial 未安裝，無法使用 Serial；將使用 ROS 2 Topic /actuator/cmd 通訊"
            )
            self._degraded = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("推桿 MCU 連線失敗（%s），自動降級為 mock 模式", exc)
            self._degraded = True
            self._serial = None

    def set_ros_bridge(self, publish_cmd, status_callback=None) -> None:
        """注入 ROS 2 通訊介面。

        Parameters
        ----------
        publish_cmd: ``Callable[[dict], None]`` — 發佈至 ``/actuator/cmd``
        status_callback: ``Callable[[dict], None]`` — 接收 ``/actuator/status``
        """
        self._publish_cmd = publish_cmd
        if status_callback is not None:
            status_callback(self._on_ros_status)
        logger.info("推桿已綁定 ROS 2 Topic：/actuator/cmd")

    def _on_ros_status(self, data: dict[str, Any]) -> None:
        """接收 MCU 經 ROS 2 Topic 回傳的狀態。"""
        self._latest_status = data

    def close(self) -> None:
        """釋放序列埠資源。"""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None

    @property
    def is_real(self) -> bool:
        """是否使用真實推桿（Serial 已連線或已綁定 ROS 2 Topic）。"""
        return self._serial is not None or self._publish_cmd is not None

    # ---------------- 核心：按壓 ----------------
    def press(self, press_duration_ms: int) -> TactileResult:
        """按壓按鈕並等待觸覺回饋。

        Parameters
        ----------
        press_duration_ms: 按壓持續時間（由中央大腦策略提供）

        Returns
        -------
        TactileResult 含 confirmed（微動開關是否觸發）與 force_kg
        """
        if self._serial is not None:
            result = self._press_serial(press_duration_ms)
            if result is not None:
                return result

        if self._publish_cmd is not None:
            result = self._press_ros(press_duration_ms)
            if result is not None:
                return result

        return self._press_mock(press_duration_ms)

    # ---------------- real：Serial ----------------
    def _press_serial(self, press_duration_ms: int) -> Optional[TactileResult]:  # pragma: no cover
        """透過序列埠與 MCU 溝通。"""
        cmd = {"cmd": "press", "duration_ms": press_duration_ms}
        try:
            self._serial.write((json.dumps(cmd) + "\n").encode("utf-8"))

            deadline = time.monotonic() + self.command_timeout_sec
            while time.monotonic() < deadline:
                line = self._serial.readline()
                if not line:
                    continue
                try:
                    resp = json.loads(line.decode("utf-8", "replace").strip())
                except json.JSONDecodeError:
                    continue
                if "tactile_ok" in resp:
                    return TactileResult(
                        confirmed=bool(resp["tactile_ok"]),
                        press_duration_ms=press_duration_ms,
                        force_kg=float(resp.get("force_kg", 0.0)),
                        sensor=resp.get("sensor", "micro_switch"),
                        threshold_kg=self.force_threshold_kg,
                        elapsed_ms=float(resp.get("actual_ms", press_duration_ms)),
                    )

            logger.warning("推桿等待 MCU 回應逾時（%.1fs）", self.command_timeout_sec)
            return TactileResult(
                confirmed=False, press_duration_ms=press_duration_ms,
                sensor="timeout", threshold_kg=self.force_threshold_kg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("推桿 Serial 通訊失敗（%s），退回模擬", exc)
            return None

    # ---------------- real：ROS 2 Topic ----------------
    def _press_ros(self, press_duration_ms: int) -> Optional[TactileResult]:
        """透過 ROS 2 Topic 與 MCU 橋接節點溝通。"""
        cmd = {"cmd": "press", "duration_ms": press_duration_ms}
        self._latest_status = {}
        try:
            self._publish_cmd(cmd)
        except Exception as exc:  # noqa: BLE001
            logger.warning("推桿 ROS 2 發佈失敗（%s），退回模擬", exc)
            return None

        deadline = time.monotonic() + self.command_timeout_sec
        while time.monotonic() < deadline:
            resp = self._latest_status
            if resp and "tactile_ok" in resp:
                return TactileResult(
                    confirmed=bool(resp["tactile_ok"]),
                    press_duration_ms=press_duration_ms,
                    force_kg=float(resp.get("force_kg", 0.0)),
                    sensor=resp.get("sensor", "micro_switch"),
                    threshold_kg=self.force_threshold_kg,
                    elapsed_ms=float(resp.get("actual_ms", press_duration_ms)),
                )
            time.sleep(0.02)

        logger.warning("推桿等待 ROS 2 狀態逾時（%.1fs）", self.command_timeout_sec)
        return TactileResult(
            confirmed=False, press_duration_ms=press_duration_ms,
            sensor="timeout", threshold_kg=self.force_threshold_kg,
        )

    # ---------------- mock ----------------
    def _press_mock(self, press_duration_ms: int) -> TactileResult:
        """模擬按壓與力感測器回應。"""
        started = time.monotonic()
        # 縮短等待以便 demo（實際按壓時間仍記錄在回傳中）
        time.sleep(min(press_duration_ms / 1000.0, 0.6))

        # 模擬 3% 機率按壓失敗（機械臂偏移或按鈕卡住）
        detected = self._rng.random() > 0.03
        force = round(self._rng.uniform(4.2, 9.8), 2) if detected else 0.0

        return TactileResult(
            confirmed=detected,
            press_duration_ms=press_duration_ms,
            force_kg=force,
            sensor="force_torque" if detected else "none",
            threshold_kg=self.force_threshold_kg,
            elapsed_ms=(time.monotonic() - started) * 1000.0,
        )


# =====================================================================
# 3. MecanumBaseInterface — 麥克納姆輪底盤 + 電梯感知
# =====================================================================
class MecanumBaseInterface:
    """麥克納姆輪底盤介面。

    麥克納姆輪的核心優勢是**平面全向移動**，可在不轉身的情況下
    以 ``linear.y``（左右橫移）微調對準電梯按鈕——
    這在傳統差速驅動底盤上是做不到的。

    ``mock``
        以計時器推進模擬各階段耗時。
    ``real``
        發佈 ``geometry_msgs/Twist`` 至 ``/cmd_vel``：

        ==================  ==========================================
        ``linear.x``       前後移動（進出電梯、樓層內巡檢）
        ``linear.y``       左右橫移（對準按鈕，來自 offset_x_px）
        ``angular.z``      原地旋轉
        ==================  ==========================================

        並訂閱 ``/scan`` 或門磁感測器判斷電梯門開關。
    """

    def __init__(self, mode: Optional[str] = None) -> None:
        self.mode = mode or get_hardware_mode()
        self.max_linear_y = float(_env_str("MAX_LINEAR_Y", "0.15"))
        self.pixel_to_meter = float(_env_str("PIXEL_TO_METER", "0.0005"))
        self.door_timeout_sec = float(_env_str("DOOR_TIMEOUT_SEC", "30.0"))
        # 門開／門關的距離門檻（依學校大樓走廊尺度）
        self.door_open_distance_m = float(_env_str("DOOR_OPEN_DISTANCE_M", "2.0"))
        self.door_closed_distance_m = float(_env_str("DOOR_CLOSED_DISTANCE_M", "1.2"))
        self._publish_cmd_vel = None      # 由呼叫端注入
        self._latest_scan = None          # 由呼叫端注入
        self._in_cabin_hint: Optional[bool] = None   # 由電梯模擬節點提供
        self._degraded = False
        self._battery = 100.0

        if self.mode in (HardwareMode.REAL, HardwareMode.GAZEBO) and self._publish_cmd_vel is None:
            logger.warning(
                "HARDWARE_MODE=%s 但尚未注入 /cmd_vel publisher；"
                "請呼叫 set_ros_bridge() 綁定底盤介面", self.mode
            )

    def set_ros_bridge(self, publish_cmd_vel, scan_callback=None) -> None:
        """注入 ROS 2 通訊介面。

        Parameters
        ----------
        publish_cmd_vel: ``Callable[[dict], None]`` — 發佈 Twist 至 ``/cmd_vel``
        scan_callback: ``Callable[[Any], None]`` — 接收 ``/scan`` (LaserScan)
        """
        self._publish_cmd_vel = publish_cmd_vel
        if scan_callback is not None:
            scan_callback(self._on_scan)
        logger.info("麥克納姆輪底盤已綁定 ROS 2 Topic：/cmd_vel")

    def _on_scan(self, data: Any) -> None:
        """接收 LiDAR 掃描資料。"""
        self._latest_scan = data

    @property
    def is_real(self) -> bool:
        """是否使用真實底盤。"""
        return self._publish_cmd_vel is not None

    # ---------------- 速度指令 ----------------
    def move(self, linear_x: float = 0.0, linear_y: float = 0.0,
             angular_z: float = 0.0) -> None:
        """發佈速度指令（real 模式）；mock 模式記錄但不下達。"""
        cmd = {
            "linear": {"x": round(linear_x, 4), "y": round(linear_y, 4), "z": 0.0},
            "angular": {"x": 0.0, "y": 0.0, "z": round(angular_z, 4)},
        }
        if self._publish_cmd_vel is not None:
            try:
                self._publish_cmd_vel(cmd)
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("底盤 /cmd_vel 發佈失敗（%s）", exc)

    def stop(self) -> None:
        """立即停止。"""
        self.move(0.0, 0.0, 0.0)

    def strafe_to_align(self, offset_x_px: int, steps: int = 1) -> None:
        """依視覺偏移量左右橫移對準按鈕。

        這是麥克納姆輪的關優勢：無需轉身，直接以 ``linear.y`` 平移修正水平誤差。

        Parameters
        ----------
        offset_x_px: 按鈕相對於預期位置的水平偏移（正值表示偏右）
        steps: 分几步逼近，避免一次移動過衝
        """
        distance_m = -offset_x_px * self.pixel_to_meter * steps
        speed = max(-self.max_linear_y, min(self.max_linear_y, distance_m / 0.5))
        logger.info(
            "麥克納姆輪橫移對準：offset_x=%dpx → linear.y=%.4f m/s", offset_x_px, speed
        )
        self.move(linear_x=0.0, linear_y=speed, angular_z=0.0)

    # ---------------- 電梯感知 ----------------
    def wait_for_door(self, timeout_sec: Optional[float] = None) -> bool:
        """等待電梯門開啟。

        ``real``
            依據 ``/scan`` 判斷前方是否有障礙物（電梯開門後通道打通），
            或由外部注入的門磁感測器狀態判定。
        ``mock``
            以固定等待時間模擬。
        """
        timeout = timeout_sec if timeout_sec is not None else self.door_timeout_sec
        started = time.monotonic()

        if self.mode in (HardwareMode.REAL, HardwareMode.GAZEBO) and self._latest_scan is not None:
            while time.monotonic() - started < timeout:
                if self._is_door_open_from_scan():
                    logger.info(
                        "偵測到電梯門開啟（LiDAR 正前方淨空 %.2fm ≥ %.2fm）",
                        self._front_median_distance() or -1.0, self.door_open_distance_m,
                    )
                    return True
                time.sleep(0.1)
            logger.warning("等待電梯開門逾時（%.1fs）", timeout)
            return False

        # mock：模擬開門等待
        time.sleep(min(timeout, 2.5))
        return True

    def _is_door_open_from_scan(self) -> bool:
        """由 LiDAR 掃描判斷電梯門是否開啟。

        採用**正前方扇區的中位數距離**而非最大值或平均值：

        * 最大值（``np.any``）會被角落縫隙誤觸發
        * 中位數對單點雜訊與偶發漏測穩健，且語意正確（「正前方淨空距離」）

        判斷門開關的典型距離（依學校大樓走廊尺度）：

        ==============  =========================================
        ``> 2.0 m``    門開（可看穿至車廂深處 / 走廊盡頭）
        ``< 1.2 m``    門關（前方就是門板）
        ==============  =========================================
        """
        front = self._front_median_distance()
        if front is None:
            return False
        return front >= self.door_open_distance_m

    def _front_median_distance(self) -> Optional[float]:
        """取出正前方扇區的中位數距離（公尺）。

        相容兩種輸入格式：
        * ``sensor_msgs/LaserScan`` 物件（有 ``.ranges`` 屬性）
        * 已解析的 dict（``{"ranges": [...], ...}``）

        重要：LaserScan 角度由 ``angle_min`` 遞增，
        **正前方（0°）位於陣列中央而非開頭**。
        若誤取 ``data[:n]`` 會讀到後方掃描資料，門開關判斷會完全錯誤。
        """
        if self._latest_scan is None:
            return None

        ranges = getattr(self._latest_scan, "ranges", None)
        if ranges is None and isinstance(self._latest_scan, dict):
            ranges = self._latest_scan.get("ranges")
        if ranges is None or np is None:
            return None

        try:
            data = np.asarray(list(ranges), dtype=float)
            if data.size == 0:
                return None

            # 正前方扇區（約 ±20 度），排除 NaN/inf 後取中位數
            # 注意：0° 位於陣列中央，不可取 data[:n]
            center = data.size // 2
            half = max(1, int(data.size * 0.055))
            front = data[max(0, center - half): center + half]
            front_valid = front[np.isfinite(front)]
            if front_valid.size == 0:
                all_valid = data[np.isfinite(data)]
                return float(np.median(all_valid)) if all_valid.size else None

            return float(np.median(front_valid))
        except Exception as exc:  # noqa: BLE001
            logger.debug("解析 /scan 失敗：%s", exc)
            return None

    def front_distance(self) -> Optional[float]:
        """公開正前方距離（除錯與儀表板顯示用）。"""
        return self._front_median_distance()

    def is_in_cabin(self) -> bool:
        """判斷是否已進入電梯車廂。

        Digital Twin 情境：由 ``elevator_sim_node`` 發佈的
        ``/elevator/sim_state`` 車廂感測結果判定；
        無法取得時退回以 LiDAR 正前方距離推測。
        """
        if self.mode in (HardwareMode.REAL, HardwareMode.GAZEBO):
            if self._in_cabin_hint is not None:
                return bool(self._in_cabin_hint)
            front = self._front_median_distance()
            if front is not None:
                # 車廂內：四面近距，淨空明顯小於走廊
                return front < 2.0
        return True    # mock：預設成功

    def drain_battery(self, amount: float) -> None:
        """模擬耗電。"""
        self._battery = max(0.0, self._battery - amount)

    def recharge(self, amount: float) -> None:
        """補充電量。"""
        self._battery = min(100.0, self._battery + amount)

    def get_status(self) -> BaseStatus:
        """取得底盤狀態。"""
        return BaseStatus(battery_percent=round(self._battery, 1))


# =====================================================================
# 硬體抽象層容器
# =====================================================================
class HardwareHAL:
    """將三個硬體介面組合為單一存取點。

    ``fsm_node.py`` 與 ``button_recognizer.py`` 只與此類別互動，
    完全不需要知道底層是真實硬體還是模擬。
    """

    def __init__(self, mode: Optional[str] = None) -> None:
        self.mode = mode or get_hardware_mode()
        self.camera = CameraInterface(self.mode)
        self.actuator = ActuatorInterface(self.mode)
        self.base = MecanumBaseInterface(self.mode)

        logger.info(
            "硬體抽象層就緒：mode=%s 相機=%s 推桿=%s 底盤=%s",
            self.mode,
            "real" if self.camera.is_real else "mock",
            "real" if self.actuator.is_real else "mock",
            "real" if self.base.is_real else "mock",
        )

    def describe(self) -> dict[str, Any]:
        """回傳硬體狀態描述（供 /robot_status 上報）。"""
        return {
            "hardware_mode": self.mode,
            "camera": {
                "ready": self.camera.is_real,
                "device": self.camera.device,
                "template_dir": self.camera.template_dir,
            },
            "actuator": {
                "ready": self.actuator.is_real,
                "port": self.actuator.serial_port,
                "baud": self.actuator.serial_baud,
            },
            "base": {
                "ready": self.base.is_real,
                "type": "mecanum_wheels",
                "max_linear_y": self.base.max_linear_y,
            },
        }

    def close(self) -> None:
        """釋放所有硬體資源。"""
        self.camera.close()
        self.actuator.close()

    def __enter__(self) -> "HardwareHAL":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


# 全域單例（模擬 fsm_node / button_recognizer 共用同一套硬體）
_HAL: Optional[HardwareHAL] = None


def get_hal() -> HardwareHAL:
    """取得全域 HAL 單例（延遲建立）。"""
    global _HAL
    if _HAL is None:
        _HAL = HardwareHAL()
    return _HAL


def reset_hal() -> None:
    """重建 HAL（測試用）。"""
    global _HAL
    if _HAL is not None:
        _HAL.close()
    _HAL = None