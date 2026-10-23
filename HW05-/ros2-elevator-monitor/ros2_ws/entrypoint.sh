#!/usr/bin/env bash
# =====================================================================
# ros2-bridge 容器啟動腳本
#   1. 載入 ROS 2 Humble 與工作區環境
#   2. 啟動 rosbridge_server (WebSocket 9090)
#   3. 啟動 bridge_rest_node  (REST 8080，供 web-backend 下指令)
#   4. 啟動 fsm_node         (跨樓層巡檢狀態機 - Step 3)
#   5. 啟動 button_recognizer (按鈕視覺/觸覺雙重確認 - Step 3)
#
# 設計重點：若某個節點尚未實作（例如 Step 3 尚未完成），
#          會自動略過並列印警告，不會讓整個容器啟動失敗。
# =====================================================================

# 注意：不可使用 set -u (nounset)
# ROS 2 的 setup.bash 會讀取未定義的環境變數（如 AMENT_TRACE_SETUP_FILES），
# 啟用 nounset 會導致容器以 "unbound variable" 錯誤退出。
# 同時不啟用 pipefail，避免 tail | sed 的日誌串流在程序結束時干擾主流程。
set -eo pipefail
set +o pipefail

# ---------- 環境變數（可由 docker-compose 覆寫）----------
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}"
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
export ROS_BRIDGE_REST_PORT="${ROS_BRIDGE_REST_PORT:-8080}"
export ROSBRIDGE_WS_PORT="${ROSBRIDGE_WS_PORT:-9090}"
export ROS_WS_DIR="${ROS_WS_DIR:-/ros2_ws}"
export ROBOT_NAME="${ROBOT_NAME:-amr-proto-01}"
export DEFAULT_FLOOR="${DEFAULT_FLOOR:-1F}"
# 中央大腦知識快取有效時間（秒）；0 = 每次都重新拉取
export KNOWLEDGE_TTL_SEC="${KNOWLEDGE_TTL_SEC:-300}"

log() { echo "[entrypoint][$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ---------- 載入 ROS 2 與工作區 ----------
# shellcheck disable=SC1091
source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

if [ ! -f "${ROS_WS_DIR}/install/setup.bash" ]; then
  log "工作區尚未建置，執行 colcon build ..."
  cd "${ROS_WS_DIR}" && colcon build --symlink-install --packages-select elevator_inspection
fi

# shellcheck disable=SC1091
source "${ROS_WS_DIR}/install/setup.bash"

log "ROS_DISTRO=${ROS_DISTRO}  ROS_DOMAIN_ID=${ROS_DOMAIN_ID}  RMW=${RMW_IMPLEMENTATION}"
log "機器人識別碼 ROBOT_NAME=${ROBOT_NAME}  中央知識快取=${KNOWLEDGE_TTL_SEC}s"

# ---------- 背景服務程序清理 ----------
PIDS=()
cleanup() {
  log "收到結束訊號，關閉所有子程序 ..."
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

# 判斷某個 console_script 是否「真的」可用
# setup.py 會預先註冊所有 console_scripts，即使對應的 .py 尚未實作也會出現在清單中，
# 因此除了比對 executable 名稱，還要確認 Python 模組檔確實存在。
has_executable() {
  local exe="$1"
  ros2 pkg executables elevator_inspection 2>/dev/null | awk '{print $2}' | grep -qx "${exe}" || return 1
  [ -f "${ROS_WS_DIR}/src/elevator_inspection/elevator_inspection/${exe}.py" ] || return 1
  return 0
}

# 啟動 ROS 2 節點（不存在時略過）
# 注意：不可使用 `cmd &> >(sed ...)`，在部分 shell 設定下會造成輸出遺失，
#       改用獨立日誌檔案再由 tail 輸出，確保錯誤訊息不會被吞掉。
LAUNCH_LOG_DIR="${ROS_WS_DIR}/log/launch"
mkdir -p "${LAUNCH_LOG_DIR}"

launch_node() {
  local exe="$1"
  local tag="$2"
  if has_executable "${exe}"; then
    log "啟動 ${exe} ..."
    local logfile="${LAUNCH_LOG_DIR}/${exe}.log"
    ros2 run elevator_inspection "${exe}" > "${logfile}" 2>&1 &
    PIDS+=($!)
    # 將節點日誌串流到主控台（帶前綴），方便 docker logs 觀察
    tail -f "${logfile}" 2>/dev/null | sed -u "s|^|[${tag}] |" &
    PIDS+=($!)
  else
    log "略過 ${exe}（尚未實作，Step 3）"
  fi
}

# ---------- 1. rosbridge_server (WebSocket 9090) ----------
log "啟動 rosbridge_server (ws://0.0.0.0:${ROSBRIDGE_WS_PORT}) ..."
ROSBRIDGE_LOG="${LAUNCH_LOG_DIR}/rosbridge_server.log"
ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
  port:="${ROSBRIDGE_WS_PORT}" \
  address:=0.0.0.0 \
  > "${ROSBRIDGE_LOG}" 2>&1 &
PIDS+=($!)
tail -f "${ROSBRIDGE_LOG}" 2>/dev/null | sed -u 's/^/[rosbridge] /' &
PIDS+=($!)

# ---------- 2. REST 控制端點（web-backend -> ROS 2 指令通道）----------
launch_node bridge_rest_node rest

# ---------- 3. 核心控制節點（Step 3）----------
# 注意：setup.py 已註冊 console_scripts，但 .py 檔尚未實作時執行會立即失敗。
#       這裡額外檢查 Python 模組檔是否存在，避免「啟動即崩潰」導致容器重啟迴圈。
launch_node fsm_node fsm
launch_node button_recognizer button

# ---------- 5. Digital Twin：電梯模擬環境（WP 1）----------
# 僅在 gazebo 模式或明確指定時啟動；mock / real 模式不會啟動
if [ "${HARDWARE_MODE:-mock}" = "gazebo" ] || [ "${START_ELEVATOR_SIM:-false}" = "true" ]; then
  launch_node elevator_sim_node elevsim
fi

log "已啟動程序 PID: ${PIDS[*]}"
log "ws://0.0.0.0:${ROSBRIDGE_WS_PORT}  |  http://0.0.0.0:${ROS_BRIDGE_REST_PORT}/health"

# 等待任一子程序結束即整體退出（交由 Docker restart 策略重啟）
wait -n
log "某個子程序已結束，容器將退出並由 Docker 重新啟動。"
exit 1