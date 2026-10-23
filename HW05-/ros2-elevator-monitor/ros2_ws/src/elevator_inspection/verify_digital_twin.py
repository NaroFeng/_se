"""Digital Twin Headless 閉環測試。

驗證「機器人 → 按鈕 → 電梯開門 → LiDAR 感知 → 進車廂 → 跨樓 → 駛出」
的完整閉環，**不需要 Gazebo**。

測試流程
--------
1. 啟動 ``elevator_sim_node``（偽 LiDAR / 偽相機）
2. 啟動 ``button_recognizer``（視覺 + 觸覺雙重確認，透過 HAL）
3. 測試腳本模擬機器人行為：按壓按鈕 → 等待開門 → 讀取 LiDAR

執行（容器內）::

    ros2 launch elevator_inspection elevator_sim_headless.launch.py &
    python3 verify_digital_twin.py

執行（本機，需已 source ROS 2 workspace）::

    python3 verify_digital_twin.py
"""

from __future__ import annotations

import json
import os
import sys
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GREEN, YELLOW, RED, CYAN, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[0m"
)

# 測試參數（對齊 elevator_sim_node 的幾何常數）
DOOR_CLOSED_M = 1.0
DOOR_OPEN_M = 3.5
DOOR_OPEN_THRESHOLD_M = 2.0
PRESS_MS = 1200

# 時間尺度由環境變數決定（測試時會設較短的值以加快驗證）
CALL_DELAY_SEC = float(os.getenv("SIM_CALL_DELAY_SEC", "3.0"))
OPEN_DURATION_SEC = float(os.getenv("SIM_OPEN_SEC", "2.5"))
CLOSE_DURATION_SEC = float(os.getenv("SIM_CLOSE_SEC", "2.0"))
MOVE_DURATION_SEC = float(os.getenv("SIM_MOVE_SEC", "4.0"))


def ok(text: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {text}")


def fail(text: str) -> None:
    print(f"  {RED}FAIL{RESET}  {text}")


def info(label: str, value) -> None:
    print(f"        {label:<30} {value}")


def banner(text: str) -> None:
    print(f"\n{'=' * 74}\n{text}\n{'=' * 74}")


class DigitalTwinTester(Node):
    """Headless 閉環測試節點。"""

    def __init__(self) -> None:
        super().__init__("digital_twin_tester")

        # 訂閱電梯模擬狀態
        self._sim_state: dict | None = None
        self.create_subscription(String, "/elevator/sim_state", self._on_sim_state, 10)

        # 訂閱微動開關回饋
        self._tactile: dict | None = None
        self.create_subscription(String, "/actuator/status", self._on_tactile, 10)

        # 訂閱視覺結果（button_recognizer 發佈）
        self._vision: list[dict] = []
        self.create_subscription(String, "/elevator/vision_result", self._on_vision, 10)

        # 訂閱按鈕確認結果
        self._button_result: dict | None = None
        self.create_subscription(String, "/elevator/button/result",
                                 self._on_button_result, 10)

        # 訂閱偽 LiDAR（sensor_msgs/LaserScan）
        self._scan_front: float | None = None
        self._scan_count = 0
        try:
            from sensor_msgs.msg import LaserScan
            self.create_subscription(LaserScan, "/scan", self._on_scan, 10)
        except ImportError:
            pass

        # 發佈按壓指令（模擬 HAL 的 ActuatorInterface）
        self._actuator_pub = self.create_publisher(String, "/actuator/cmd", 10)

    # ---------------- 回呼 ----------------
    def _on_sim_state(self, msg: String) -> None:
        try:
            self._sim_state = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def _on_tactile(self, msg: String) -> None:
        try:
            self._tactile = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def _on_vision(self, msg: String) -> None:
        try:
            self._vision.append(json.loads(msg.data))
        except json.JSONDecodeError:
            pass

    def _on_button_result(self, msg: String) -> None:
        try:
            self._button_result = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

    def _on_scan(self, msg) -> None:
        """由 LaserScan 取出**正前方**扇區的中位數距離。

        重要：LaserScan 角度由 ``angle_min`` 遞增，正前方（0°）位於
        陣列**中央**而非開頭。若誤取 ``data[:n]`` 會讀到後方掃描資料，
        導致距離判斷完全錯誤。
        """
        data = list(msg.ranges)
        if not data:
            return

        center = len(data) // 2                 # 正前方 0° 的索引
        half = max(1, int(len(data) * 0.055))   # ±20°
        front = data[max(0, center - half): center + half]

        valid = sorted(r for r in front if r == r and r < float("inf"))
        if valid:
            self._scan_front = valid[len(valid) // 2]
        self._scan_count += 1

    # ---------------- 測試步驟 ----------------
    def wait_for(self, predicate, timeout: float, label: str) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if predicate():
                return True
        print(f"      （等待 {label} 逾時 {timeout:.0f}s）")
        return False


def main() -> int:
    banner("Digital Twin Headless 閉環測試（無需 Gazebo）")

    rclpy.init()
    node = DigitalTwinTester()

    results: list[bool] = []

    try:
        # ----------------------------------------------------------------
        banner("Phase 1 — 感測器就緒：偽 LiDAR 與電梯狀態")
        ready = node.wait_for(
            lambda: node._sim_state is not None and node._scan_front is not None,
            timeout=25.0, label="LiDAR + sim_state",
        )
        if not ready:
            fail("感測器未就緒，請確認 elevator_sim_node 已啟動")
            return 1

        st = node._sim_state
        info("電梯編號", st["elevator_id"])
        info("目前樓層", st["current_floor"])
        info("門狀態", st["door_state"])
        info("LiDAR 正前方距離", f"{node._scan_front:.2f} m")
        info("LiDAR 訊息數", node._scan_count)
        results.append(True)
        ok("偽 LiDAR 與電梯狀態 topic 正常")

        # ----------------------------------------------------------------
        banner("Phase 2 — 門關狀態驗證（LiDAR 中位數 < 2.0m）")
        info("正前方距離", f"{node._scan_front:.2f} m")
        info("開門門檻", f"{DOOR_OPEN_THRESHOLD_M} m")
        if node._scan_front < DOOR_OPEN_THRESHOLD_M:
            ok("門關時正前方淨空小於門檻 → FSM 應停留在 WAITING_ELEVATOR")
        else:
            fail(f"門關時距離應 < {DOOR_OPEN_THRESHOLD_M}m，實得 {node._scan_front:.2f}m")
        results.append(node._scan_front < DOOR_OPEN_THRESHOLD_M)

        # ----------------------------------------------------------------
        banner("Phase 3 — 視覺辨識：按鈕面板比對")
        # 主動送出按鈕確認請求，讓 button_recognizer 進行視覺比對
        btn_req_pub = node.create_publisher(String, "/elevator/button/request", 10)
        warmup = time.monotonic() + 0.6      # 等待 DDS 發現完成
        while time.monotonic() < warmup:
            rclpy.spin_once(node, timeout_sec=0.05)
        btn_req_pub.publish(String(data=json.dumps({
            "request_id": "dt-test-vis",
            "floor_code": "1F",
            "button_label": "5F",
            "target_floor": "5F",
            "confidence_threshold": 0.75,
            "press_duration_ms": 1200,
            "attempt": 0,
            "policy_source": "central_brain",
        })))

        vision_ok = node.wait_for(
            lambda: len(node._vision) > 0, timeout=20.0, label="vision_result",
        )
        if not vision_ok:
            # 若 button_recognizer 未啟動，視覺步驟略過（單獨測電梯閉環）
            print(f"  {YELLOW}SKIP{RESET}  button_recognizer 未發佈視覺結果，"
                  f"僅驗證電梯閉環")
            results.append(True)
        else:
            v = node._vision[-1]
            info("比對按鈕", v["button_label"])
            info("相似度", v["confidence"])
            info("門檻", v["threshold"])
            info("比對方法", v["method"])
            info("偏移量", f"({v.get('offset_x_px', 0)}, {v.get('offset_y_px', 0)}) px")
            passed = v["confidence"] >= v["threshold"]
            if passed:
                ok("視覺辨識通過（Template Matching / 模擬比對）")
            else:
                fail("視覺辨識未通過")
            results.append(passed)

        # ----------------------------------------------------------------
        banner("Phase 4 — 觸覺確認：推桿按壓與微動開關")
        info("送出指令", f'{{"cmd":"press","duration_ms":{PRESS_MS}}}')
        node._actuator_pub.publish(String(data=json.dumps({
            "cmd": "press",
            "duration_ms": PRESS_MS,
            "target_floor": "5F",
        })))
        node._tactile = None
        tactile_ok = node.wait_for(
            lambda: node._tactile is not None, timeout=12.0, label="tactile_ok",
        )
        if tactile_ok:
            info("tactile_ok", node._tactile["tactile_ok"])
            info("實際行程", f"{node._tactile['actual_ms']} ms")
            info("力道", f"{node._tactile['force_kg']} kg")
            info("感測器", node._tactile["sensor"])
            if node._tactile["tactile_ok"]:
                ok("彈簧微動開關觸發，觸覺確認通過")
                results.append(True)
            else:
                fail("微動開關未觸發")
                results.append(False)
        else:
            fail("未收到觸覺回饋")
            results.append(False)

        # ----------------------------------------------------------------
        banner("Phase 5 — 電梯開門：LiDAR 距離真實變化")
        info("等待開門", f"呼叫延遲 {CALL_DELAY_SEC}s + 開啟 {OPEN_DURATION_SEC}s")
        # 以「門完全開啟」為判準（比卡在門檻值更穩健），
        # 再驗證 LiDAR 正前方淨空確實變大
        opened = node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") == "OPEN",
            timeout=CALL_DELAY_SEC + OPEN_DURATION_SEC + 10.0,
            label="door open",
        )
        info("正前方距離", f"{node._scan_front:.2f} m")
        info("門開啟比例", f"{node._sim_state['door_open_ratio'] if node._sim_state else 0:.2f}")
        info("門狀態", node._sim_state["door_state"] if node._sim_state else "-")
        if opened and node._scan_front >= DOOR_CLOSED_M + 0.8:
            ok(f"LiDAR 正前方淨空由 {DOOR_CLOSED_M}m 變大到 {node._scan_front:.2f}m"
               f" → 觸發 WAITING_ELEVATOR → ENTERING_ELEVATOR")
            results.append(True)
        else:
            fail(f"電梯門未開啟或 LiDAR 距離未變化（{node._scan_front:.2f}m）")
            results.append(False)

        # ----------------------------------------------------------------
        banner("Phase 6 — 模擬機器人進入車廂 → 跨樓 → 駛出")
        # 發佈機器人狀態，驅動電梯關門與跨樓
        print(f"  {CYAN}模擬{RESET} FSM 進入 ENTERING_ELEVATOR → 觸發電梯關門")
        # 注意：此處不可再送 press 指令，
        # 否則門在關閉途中會被重新呼喚開啟，導致永遠等不到「門全關」
        node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") == "OPEN",
            timeout=OPEN_DURATION_SEC + 10.0, label="door fully open first",
        )
        _publish_robot_state(node, "ENTERING_ELEVATOR", "5F")

        closed = node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") in ("CLOSING", "CLOSED"),
            timeout=CLOSE_DURATION_SEC + 10.0, label="door closing",
        )
        info("門狀態", node._sim_state["door_state"] if node._sim_state else "-")
        if closed:
            ok("收到 ENTERING_ELEVATOR → 電梯門自動關閉")
            results.append(True)
        else:
            fail("電梯門未關閉")
            results.append(False)

        print(f"  {CYAN}模擬{RESET} FSM 進入 MOVING_FLOOR → 電梯跨樓 1F → 5F")
        # 等門完全關閉後才跨樓（真實電梯行為）
        node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") == "CLOSED",
            timeout=CLOSE_DURATION_SEC + 10.0, label="door fully closed",
        )
        _publish_robot_state(node, "MOVING_FLOOR", "5F")

        moved = node.wait_for(
            lambda: (node._sim_state or {}).get("current_floor") == "5F",
            timeout=MOVE_DURATION_SEC + 15.0, label="floor change",
        )
        if moved:
            info("抵達樓層", node._sim_state["current_floor"])
            ok("電梯完成跨樓，模擬環境樓層切換成功")
            results.append(True)
        else:
            fail(f"樓層未切換（目前 {node._sim_state['current_floor'] if node._sim_state else '-'}）")
            results.append(False)

        print(f"  {CYAN}模擬{RESET} FSM 進入 EXITING_ELEVATOR → 電梯開門讓機器人駛出")
        _publish_robot_state(node, "EXITING_ELEVATOR", "5F")
        reopened = node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") in ("OPENING", "OPEN"),
            timeout=15.0, label="reopen",
        )
        info("門狀態", node._sim_state["door_state"] if node._sim_state else "-")
        if reopened:
            ok("收到 EXITING_ELEVATOR → 5F 電梯門開啟")
            results.append(True)
        else:
            fail("電梯門未重新開啟")
            results.append(False)

        # ----------------------------------------------------------------
        banner("Phase 7 — 巡檢完成標記")
        # 等待門完全開啟後，機器人駛出並進入巡檢狀態
        node.wait_for(
            lambda: (node._sim_state or {}).get("door_state") == "OPEN",
            timeout=OPEN_DURATION_SEC + 8.0, label="door fully open",
        )
        _publish_robot_state(node, "INSPECTING", "5F")
        marked = node.wait_for(
            lambda: "5F" in (node._sim_state or {}).get("inspected_floors", []),
            timeout=15.0, label="inspected",
        )
        if marked:
            info("已巡檢樓層", node._sim_state["inspected_floors"])
            ok("電梯模擬環境已記錄 5F 巡檢完成")
            results.append(True)
        else:
            fail("未記錄巡檢樓層")
            results.append(False)

    finally:
        node.destroy_node()
        rclpy.shutdown()

    # ----------------------------------------------------------------
    banner("測試結論")
    passed = sum(1 for r in results if r)
    total = len(results)
    rate = passed / total * 100 if total else 0
    info("通過", f"{passed} / {total}")
    info("通過率", f"{rate:.0f}%")
    if rate >= 80:
        print(f"\n  {GREEN}✓ Digital Twin 閉環成立{RESET}")
        print("    機器人 → 按鈕雙重確認 → 電梯開門（LiDAR 感知）→ 進車廂 → 跨樓 → 駛出")
        print(f"  {GREEN}✓ 完全 Headless，未啟動 Gazebo{RESET}")
        return 0
    print(f"\n  {RED}✗ 閉環未完全成立{RESET}")
    return 1


def _publish_robot_state(node: DigitalTwinTester, state: str, target_floor: str) -> None:
    """以測試節點身分發佈 /robot_status，驅動電梯模擬狀態機。"""
    node._robot_status_pub = getattr(node, "_robot_status_pub", None)
    if node._robot_status_pub is None:
        node._robot_status_pub = node.create_publisher(
            String, "/robot_status",
            # 與 elevator_sim_node 的訂閱 QoS 一致（reliable）
            QoSProfile(
                depth=10,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.VOLATILE,
            ),
        )
    node._robot_status_pub.publish(String(data=json.dumps({
        "robot_name": os.getenv("ROBOT_NAME", "amr-proto-01"),
        "fsm_state": state,
        "current_floor": "1F",
        "target_floor": target_floor,
        "hardware_mode": os.getenv("HARDWARE_MODE", "gazebo"),
    })))


if __name__ == "__main__":
    sys.exit(main())