#!/usr/bin/env python3
"""bridge_rest_node：Web ↔ ROS 2 的橋接端點。

web-backend 透過 HTTP 呼叫本節點，節點再把指令轉成 ROS 2 topic 訊息，
交給 fsm_node（跨樓層巡檢狀態機）執行。

端點（PORT = ROS_BRIDGE_REST_PORT，預設 8080）：
    GET  /health         健康檢查
    GET  /status         回傳目前狀態快取（由 /robot_status topic 更新）
    POST /api/command    下達控制指令（start_inspection / goto_floor / …）
    GET  /topics         列出相關 ROS 2 topic

使用 stdlib http.server + 背景執行緒，避免與 rclpy 的 executor 互相干擾。
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# --------------------------------------------------------------------
# ROS 2 topic 定義
# --------------------------------------------------------------------
TOPIC_ROBOT_STATUS = "/robot_status"        # fsm_node -> bridge (JSON 字串)
TOPIC_COMMAND = "/inspection/command"       # bridge -> fsm_node (JSON 字串)
TOPIC_EVENT_LOG = "/inspection/event_log"   # fsm_node -> bridge (JSON 字串)

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


class BridgeRestNode(Node):
    """ROS 2 節點 + 內建 REST 控制端點。"""

    def __init__(self) -> None:
        super().__init__("bridge_rest_node")

        self._lock = threading.Lock()
        self._status: dict[str, Any] = {
            "robot_name": os.getenv("ROBOT_NAME", "amr-proto-01"),
            "fsm_state": "IDLE",
            "current_floor": os.getenv("DEFAULT_FLOOR", "1F"),
            "target_floor": None,
            "elevator_state": None,
            "map_name": None,
            "battery_percent": None,
            "mode": "auto",
            "pose": None,
            "image_topic": "/camera/color/image_raw",
            "buttons": [],
            "note": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._received_events = 0
        self._posted_events = 0
        self._failed_posts = 0
        # 待轉送至 web-backend 的巡檢事件佇列
        self._event_queue: list[dict[str, Any]] = []

        # 發佈給 fsm_node 的指令
        self._cmd_pub = self.create_publisher(String, TOPIC_COMMAND, 10)
        # 訂閱 fsm_node 狀態
        self.create_subscription(
            String, TOPIC_ROBOT_STATUS, self._on_status, 10
        )
        # 訂閱巡檢事件（後續可轉送 web-backend 寫入巡檢日誌）
        self.create_subscription(
            String, TOPIC_EVENT_LOG, self._on_event, 20
        )

        self.get_logger().info(
            f"bridge_rest_node 啟動：訂閱 {TOPIC_ROBOT_STATUS}，發佈 {TOPIC_COMMAND}"
        )

        # 背景執行緒：事件轉送 + 狀態心跳
        self._event_thread = threading.Thread(target=self._flush_events, daemon=True)
        self._status_thread = threading.Thread(target=self._push_status, daemon=True)
        self._event_thread.start()
        self._status_thread.start()

    # ---------------- ROS 回呼 ----------------
    def _on_status(self, msg: String) -> None:
        """接收 fsm_node 發佈的狀態。"""
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("無法解析 robot_status 訊息")
            return

        with self._lock:
            self._status.update(data)
            self._status["timestamp"] = datetime.now(timezone.utc).isoformat()

    def _on_event(self, msg: String) -> None:
        """接收巡檢事件，轉送至 web-backend 寫入 PostgreSQL。"""
        self._received_events += 1
        try:
            event = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        event_type = event.get("event_type", "info")
        message = event.get("message", "")
        self.get_logger().info(f"[event] {event_type} {message}")

        # 非阻塞轉送：放入佇列由背景執行緒送出，避免拖慢 ROS 回呼
        with self._lock:
            if len(self._event_queue) < 200:      # 防止記憶體無限成長
                self._event_queue.append(event)

    def _backend_url(self) -> str:
        """取得中央大腦（web-backend）網址。

        支援三種設定來源，以對應不同的部署情境：
        1. ``BACKEND_CALLBACK_URL`` — 完整心跳端點（單機 compose 部署）
        2. ``BACKEND_BASE_URL``   — 後端根網址
        3. ``BACKEND_URL``        — 車載邊緣端（docker-compose.edge.yml）
        """
        callback = os.getenv("BACKEND_CALLBACK_URL", "").strip()
        if callback:
            return callback

        base = os.getenv("BACKEND_BASE_URL", "").strip() or os.getenv("BACKEND_URL", "").strip()
        if not base:
            return ""
        return f"{base.rstrip('/')}/api/v1/system/heartbeat"

    def _flush_events(self) -> None:
        """背景執行緒：批次將巡檢事件 POST 到 web-backend。"""
        backend = self._backend_url()
        if not backend:
            return
        # BACKEND_CALLBACK_URL 為 http://backend:8000/api/v1/system/heartbeat
        # 需取出 base URL 後改打批次寫入端點
        # （單筆 /logs 收 {...}，批次 /logs/batch 收 {"logs": [...]}，格式不同）
        base = backend.split("/api/")[0] if "/api/" in backend else backend
        endpoint = f"{base}/api/v1/inspections/logs/batch"

        while rclpy.ok():
            time.sleep(0.5)
            with self._lock:
                batch = self._event_queue[:]
                self._event_queue.clear()
            if not batch:
                continue
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps({"logs": batch}, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                self._posted_events += result.get("accepted", len(batch))
            except Exception as exc:  # noqa: BLE001
                self._failed_posts += 1
                if self._failed_posts % 10 == 1:
                    self.get_logger().warning(
                        f"巡檢事件寫入後端失敗（第 {self._failed_posts} 次）：{exc}"
                    )

    def _push_status(self) -> None:
        """背景執行緒：定期將狀態推送至 web-backend（延遲最低的狀態傳遞）。"""
        backend = self._backend_url()
        if not backend:
            return
        while rclpy.ok():
            time.sleep(1.0)
            try:
                req = urllib.request.Request(
                    backend,
                    data=json.dumps(self.get_status(), ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5).close()
            except Exception as exc:  # noqa: BLE001
                if self._failed_posts % 20 == 0:
                    self.get_logger().debug(f"狀態推送失敗：{exc}")

    # ---------------- 供 REST 端點呼叫 ----------------
    def get_status(self) -> dict[str, Any]:
        with self._lock:
            data = dict(self._status)
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        data["uptime_sec"] = round(time.time() - self._created_at, 1)
        data["events_received"] = self._received_events
        data["events_posted"] = self._posted_events
        data["events_failed"] = self._failed_posts
        return data

    def publish_command(self, command: str, params: dict[str, Any],
                        request_id: str | None) -> dict[str, Any]:
        """把 HTTP 指令轉成 ROS 2 訊息發佈出去。"""
        payload = {
            "command": command,
            "params": params or {},
            "request_id": request_id,
            "issued_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cmd_pub.publish(
            String(data=json.dumps(payload, ensure_ascii=False))
        )
        self.get_logger().info(f"已發佈指令 {command} -> {TOPIC_COMMAND}")
        return payload

    # 記錄啟動時間供 uptime 使用
    _created_at = time.time()


# =====================================================================
# REST 層
# =====================================================================
def make_handler(node: BridgeRestNode) -> type[BaseHTTPRequestHandler]:
    """建立綁定到 node 的 request handler。"""

    class BridgeHandler(BaseHTTPRequestHandler):
        server_version = "ElevatorBridge/1.0"

        # ---------------- 工具 ----------------
        def _send(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:  # 簡化日誌
            # RcutilsLogger 只接受單一 message 參數，需自行格式化
            try:
                message = fmt % args
            except (TypeError, ValueError):
                message = fmt
            node.get_logger().debug(f"http - {message}")

        # ---------------- GET ----------------
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                # fsm_node 會訂閱指令 topic，訂閱者數 > 0 代表巡檢狀態機已上線
                fsm_subscribers = node.count_subscribers(TOPIC_COMMAND)
                self._send(200, {
                    "status": "ok",
                    "node": "bridge_rest_node",
                    "ros_domain_id": os.getenv("ROS_DOMAIN_ID", "?"),
                    "fsm_online": fsm_subscribers > 0,
                    "fsm_subscribers": fsm_subscribers,
                    "topics": {
                        "status": TOPIC_ROBOT_STATUS,
                        "command": TOPIC_COMMAND,
                        "event_log": TOPIC_EVENT_LOG,
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            elif path == "/status":
                self._send(200, node.get_status())
            elif path == "/topics":
                self._send(200, {"topics": [
                    TOPIC_ROBOT_STATUS, TOPIC_COMMAND, TOPIC_EVENT_LOG,
                ]})
            else:
                self._send(404, {"detail": f"未知路徑：{path}"})

        # ---------------- POST ----------------
        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path != "/api/command":
                self._send(404, {"detail": f"未知路徑：{path}"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._send(400, {"detail": "請求內容不是合法的 JSON"})
                return

            command = payload.get("command")
            if command not in ALLOWED_COMMANDS:
                self._send(422, {
                    "detail": f"不支援的指令：{command}",
                    "allowed": sorted(ALLOWED_COMMANDS),
                })
                return

            result = node.publish_command(
                command=command,
                params=payload.get("params") or {},
                request_id=payload.get("request_id"),
            )
            self._send(200, {
                "accepted": True,
                "command": command,
                "request_id": payload.get("request_id"),
                "result": result,
                "message": f"指令 {command} 已發佈至 {TOPIC_COMMAND}",
            })

        # ---------------- OPTIONS (CORS 預檢) ----------------
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    return BridgeHandler


def main(args: list[str] | None = None) -> None:
    """程式進入點。"""
    rclpy.init(args=args)
    node = BridgeRestNode()

    port = int(os.getenv("ROS_BRIDGE_REST_PORT", "8080"))
    handler = make_handler(node)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), handler)
    httpd.daemon_threads = True

    thread = threading.Thread(target=httpd.serve_forever, name="rest-api", daemon=True)
    thread.start()
    node.get_logger().info(f"REST 控制端點已啟動：http://0.0.0.0:{port}")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到 Ctrl-C，正在關閉…")
    finally:
        httpd.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()