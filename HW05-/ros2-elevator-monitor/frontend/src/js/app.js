/**
 * 前端監控儀表板
 *   - 每 2 秒輪詢 /api/v1/system/status 顯示機器人即時狀態
 *   - 載入 /api/v1/floors 顯示樓層清單並標示目前所在樓層
 *   - 載入 /api/v1/inspections/logs 顯示巡檢事件日誌
 *   - 以原生 WebSocket 連線 /rosbridge，收到影像 topic 時更新畫面
 */
(function () {
  "use strict";

  const API = "/api/v1";
  const WS_URL = (location.protocol === "https:" ? "wss://" : "ws://") +
                 location.host + "/rosbridge";

  const $ = (id) => document.getElementById(id);
  const text = (id, value) => { $(id).textContent = value ?? "-"; };

  // ------------------------------------------------------------------
  // FSM 狀態中文映射（對齊 fsm_node.py 的 State enum，9 個狀態）
  // ------------------------------------------------------------------
  const FSM_STATE_LABELS = {
    IDLE: "待機",
    APPROACHING_ELEVATOR: "前往電梯廳",
    WAITING_ELEVATOR: "等待電梯（按鈕確認）",
    ENTERING_ELEVATOR: "進入電梯",
    MOVING_FLOOR: "跨樓移動中",
    EXITING_ELEVATOR: "駛出電梯",
    INSPECTING: "巡檢作業中",
    PAUSED: "已暫停",
    ERROR: "異常停止",
  };

  const ELEVATOR_STATE_LABELS = {
    IDLE: "待機",
    CALLING: "呼叫中",
    DOOR_OPEN: "門開啟",
    IN_CABIN: "車廂內",
    MOVING: "移動中",
    PAUSED: "已暫停",
    ERROR: "異常",
  };

  /** 依 FSM 狀態套用徽章樣式 */
  function fsmBadgeClass(state) {
    if (state === "ERROR") return "error";
    if (state === "PAUSED") return "paused";
    if (state === "IDLE") return "idle";
    return "busy";
  }

  /** 依電梯狀態上色 */
  function elevatorBadgeClass(state) {
    if (state === "ERROR") return "error";
    if (state === "MOVING") return "busy";
    return "idle";
  }

  // ------------------------------------------------------------------
  // 工具
  // ------------------------------------------------------------------
  async function getJSON(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleTimeString("zh-TW", { hour12: false });
  }

  // ------------------------------------------------------------------
  // 機器人狀態
  // ------------------------------------------------------------------
  let statusOffline = true;

  async function refreshStatus() {
    try {
      const s = await getJSON(`${API}/system/status`);
      statusOffline = false;
      setConnBadge(true);

      // FSM 狀態（中文 + 徽章）
      const fsm = s.fsm_state || "UNKNOWN";
      const fsmEl = $("fsm-state");
      fsmEl.textContent = FSM_STATE_LABELS[fsm] || fsm;
      fsmEl.className = "state-chip " + fsmBadgeClass(fsm);

      // 電梯狀態（中文 + 徽章）
      const elev = s.elevator_state;
      const elevEl = $("elevator-state");
      elevEl.textContent = elev ? (ELEVATOR_STATE_LABELS[elev] || elev) : "-";
      elevEl.className = elev ? ("state-chip " + elevatorBadgeClass(elev)) : "";

      text("current-floor", s.current_floor);
      text("target-floor", s.target_floor);
      text("map-name", s.map_name);
      text("battery", s.battery_percent != null ? `${s.battery_percent}%` : "-");
      text("video-topic", `topic: ${s.image_topic || "-"}`);
      text("robot-name", s.robot_name || "-");

      // 錯誤碼提示（中央大腦 error_code）
      const errEl = $("error-box");
      if (s.error_code && s.error_code !== 0) {
        errEl.style.display = "block";
        errEl.innerHTML =
          `<strong>錯誤 ${s.error_code}</strong>：${s.error_message || "未知錯誤"}`;
      } else {
        errEl.style.display = "none";
      }

      // 巡檢進度
      const wp = s.waypoints || [];
      const idx = s.waypoint_index;
      text("waypoint", wp.length
        ? `第 ${idx + 1} / ${wp.length} 站 · 目標 ${s.target_floor || "-"}`
        : "-");

      // 控制按鈕可用性依 FSM 狀態啟用／停用
      updateControlButtons(fsm);

      const batt = s.battery_percent != null ? s.battery_percent : 0;
      $("battery-fill").style.width = `${Math.max(0, Math.min(100, batt))}%`;
      $("battery-fill").style.background =
        batt > 50 ? "var(--accent)" : batt > 20 ? "var(--warn)" : "var(--error)";

      highlightCurrentFloor(s.current_floor);
    } catch (err) {
      if (!statusOffline) setConnBadge(false);
      statusOffline = true;
      text("fsm-state", "OFFLINE");
    }
  }

  function setConnBadge(online) {
    const b = $("conn-badge");
    b.textContent = online ? "橋接連線正常" : "橋接離線";
    b.className = "badge " + (online ? "online" : "offline");
  }

  // ------------------------------------------------------------------
  // 樓層清單
  // ------------------------------------------------------------------
  async function refreshFloors() {
    try {
      const floors = await getJSON(`${API}/floors`);
      $("floor-list").innerHTML = floors.map((f) => `
        <div class="floor-item" data-code="${f.floor_code}">
          <div>
            <div class="code">${f.floor_code}</div>
            <div class="name">${f.name}</div>
          </div>
          <span class="tag">${f.has_elevator ? "電梯 " + f.elevator_id : "無電梯"}</span>
        </div>`).join("");

      const sel = $("filter-floor");
      sel.innerHTML = '<option value="">全部樓層</option>' +
        floors.map((f) => `<option value="${f.floor_code}">${f.floor_code}</option>`).join("");
    } catch (err) {
      $("floor-list").textContent = "無法載入樓層資訊";
    }
  }

  function highlightCurrentFloor(code) {
    document.querySelectorAll(".floor-item").forEach((el) => {
      el.classList.toggle("current", el.dataset.code === code);
    });
  }

  // ------------------------------------------------------------------
  // 巡檢日誌
  // ------------------------------------------------------------------
  async function refreshLogs() {
    const params = new URLSearchParams({ limit: "30" });
    const ev = $("filter-event").value;
    const fl = $("filter-floor").value;
    if (ev) params.set("event_type", ev);
    if (fl) params.set("floor_code", fl);

    try {
      const page = await getJSON(`${API}/inspections/logs?${params}`);
      const box = $("log-list");
      if (!page.items.length) {
        box.textContent = "尚無巡檢紀錄";
        return;
      }
      box.innerHTML = page.items.map((l) => `
        <div class="log-item ${l.status}">
          <div class="log-head">
            <span class="log-type">${l.event_type}</span>
            <span class="log-time">${fmtTime(l.occurred_at)}</span>
          </div>
          <div class="log-msg">${l.message || "-"}</div>
          <div class="log-meta">
            ${l.floor_code ? "樓層 " + l.floor_code : ""}
            ${l.from_floor_code && l.to_floor_code ? ` · ${l.from_floor_code} → ${l.to_floor_code}` : ""}
            ${l.duration_ms != null ? " · " + l.duration_ms + "ms" : ""}
          </div>
        </div>`).join("");
    } catch (err) {
      $("log-list").textContent = "無法載入巡檢日誌";
    }
  }

  // ------------------------------------------------------------------
  // 中央大腦自適應狀態（Central Brain Policy）
  // ------------------------------------------------------------------
  let policyOnlyLearned = false;

  async function refreshPolicy() {
    try {
      const d = await getJSON(
        `${API}/inspections/policy?only_learned=${policyOnlyLearned ? 1 : 0}&limit=60`);

      $("brain-meta").innerHTML =
        `基準值 <b>${d.base_press_ms}ms / ${d.base_threshold}</b> · ` +
        `安全範圍 <b>${d.safe_range.press_ms[0]}~${d.safe_range.press_ms[1]}ms</b> / ` +
        `<b>${d.safe_range.threshold[0]}~${d.safe_range.threshold[1]}</b><br>` +
        `已學習 <b>${d.learned_count}</b> / 共 <b>${d.total}</b> 顆按鈕`;

      const box = $("policy-list");
      if (!d.items.length) {
        box.textContent = "尚無按鈕特徵資料";
        return;
      }

      box.innerHTML = d.items.map((p) => {
        const drifted = Math.abs(p.press_drift) > 0;
        const pressCls = drifted ? "p drift" : "p base";
        const thDrifted = Math.abs(p.threshold_drift) > 0.0001;
        const thCls = thDrifted ? "p drift" : "p base";
        const itemCls = p.learned ? (p.at_base ? "policy-item converged"
                                          : "policy-item learned")
                                   : "policy-item";
        const badge = p.learned ? (p.at_base ? "已收斂" : "已學習") : "初始值";
        return `
        <div class="${itemCls}">
          <div class="policy-row">
            <span class="code">${p.floor_code} → ${p.button_label}</span>
            <span class="src">${p.policy_source} · ${badge}</span>
          </div>
          <div class="policy-params">
            <span class="${pressCls}">按壓 ${p.press_duration_ms}ms${drifted ? ` (${p.press_drift > 0 ? "+" : ""}${p.press_drift})` : ""}</span>
            <span class="${thCls}">門檻 ${p.confidence_threshold}</span>
          </div>
          ${p.reason ? `<div class="policy-reason">↳ ${p.reason}</div>` : ""}
        </div>`;
      }).join("");
    } catch (err) {
      $("policy-list").textContent = "無法載入中央大腦策略";
    }
  }

  // ------------------------------------------------------------------
  // 控制指令（對齊 fsm_node.py 支援的指令）
  // ------------------------------------------------------------------
  async function sendCommand(command, params = {}) {
    try {
      const r = await fetch(`${API}/system/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command, params }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      showToast(`指令 ${command} 已送出`, "ok");
      setTimeout(refreshStatus, 400);
      return await r.json();
    } catch (err) {
      showToast(`指令 ${command} 失敗：${err.message}`, "err");
      return null;
    }
  }

  let toastTimer = null;
  function showToast(msg, kind) {
    const t = $("toast");
    t.textContent = msg;
    t.className = "toast show " + (kind || "ok");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.className = "toast"; }, 2600);
  }

  /** 依 FSM 狀態啟用／停用控制按鈕 */
  function updateControlButtons(fsm) {
    const idle = fsm === "IDLE";
    const running = ["APPROACHING_ELEVATOR", "WAITING_ELEVATOR",
      "ENTERING_ELEVATOR", "MOVING_FLOOR", "EXITING_ELEVATOR",
      "INSPECTING"].includes(fsm);
    const paused = fsm === "PAUSED";
    const errored = fsm === "ERROR";

    $("btn-start").disabled = !idle;
    $("btn-pause").disabled = !running;
    $("btn-resume").disabled = !paused;
    $("btn-stop").disabled = !(running || paused);
    $("btn-reset").disabled = !errored;
  }

  // ------------------------------------------------------------------
  // 統計
  // ------------------------------------------------------------------
  async function refreshStats() {
    try {
      const s = await getJSON(`${API}/inspections/summary?days=7`);
      $("stat-grid").innerHTML = `
        <div class="stat-card"><div class="num">${s.total_events}</div><div class="cap">7 天事件</div></div>
        <div class="stat-card"><div class="num">${s.total_inspections}</div><div class="cap">巡檢任務</div></div>
        <div class="stat-card"><div class="num">${s.success_rate}%</div><div class="cap">成功率</div></div>
        <div class="stat-card"><div class="num">${s.error_events}</div><div class="cap">錯誤數</div></div>
        <div class="stat-card"><div class="num">${s.success_inspections}</div><div class="cap">成功任務</div></div>
        <div class="stat-card"><div class="num">${s.failed_inspections}</div><div class="cap">失敗任務</div></div>`;
    } catch (err) {
      $("stat-grid").textContent = "無法載入統計";
    }
  }

  // ------------------------------------------------------------------
  // rosbridge WebSocket（影像串流 / 即時 topic）
  // ------------------------------------------------------------------
  let ws = null;
  let wsRetry = 2000;
  let frameCount = 0;
  let fpsTimer = null;

  function connectRosbridge() {
    try {
      ws = new WebSocket(WS_URL);
    } catch (err) {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      wsRetry = 2000;
      ws.send(JSON.stringify({ op: "subscribe", topic: "/camera/color/image_raw" }));
      ws.send(JSON.stringify({ op: "subscribe", topic: "/robot_status" }));
    };

    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data);
        if (msg.op === "publish" && msg.topic === "/robot_status") {
          refreshStatus();
        }
      } catch (err) { /* 忽略非 JSON 訊息 */ }
    };

    ws.onclose = () => { setConnBadge(false); scheduleReconnect(); };
    ws.onerror = () => { try { ws.close(); } catch (e) {} };
  }

  function scheduleReconnect() {
    setTimeout(connectRosbridge, wsRetry);
    wsRetry = Math.min(wsRetry * 2, 30000);
  }

  function startFpsCounter() {
    if (fpsTimer) return;
    fpsTimer = setInterval(() => {
      text("video-fps", frameCount > 0 ? `${frameCount} frames/2s` : "等待影像");
      frameCount = 0;
    }, 2000);
  }

  /** 將 ROS Image (sensor_msgs/Image) 或 base64 影像轉成 <img> 可用的來源。 */
  function applyImage(msg) {
    const img = $("camera-img");
    if (msg.data && msg.data.startsWith("data:image")) {
      img.src = msg.data;
      frameCount++;
    } else if (msg.data) {
      try {
        const bytes = atob(msg.data);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const blob = new Blob([arr], { type: msg.format || "image/jpeg" });
        img.src = URL.createObjectURL(blob);
        frameCount++;
      } catch (err) { /* base64 解碼失敗 */ }
    }
  }

  // ------------------------------------------------------------------
  // 啟動
  // ------------------------------------------------------------------
  function tickClock() {
    text("clock", new Date().toLocaleTimeString("zh-TW", { hour12: false }));
  }

  window.addEventListener("DOMContentLoaded", () => {
    refreshFloors();
    refreshLogs();
    refreshStats();
    refreshStatus();
    refreshPolicy();

    setInterval(refreshStatus, 2000);
    setInterval(refreshLogs, 5000);
    setInterval(refreshStats, 30000);
    setInterval(refreshPolicy, 8000);   // 中央大腦策略變化較慢
    setInterval(tickClock, 1000);

    $("refresh-btn").addEventListener("click", () => {
      refreshFloors(); refreshLogs(); refreshStats(); refreshStatus(); refreshPolicy();
    });
    $("filter-event").addEventListener("change", refreshLogs);
    $("filter-floor").addEventListener("change", refreshLogs);

    // 中央大腦策略：篩選切換
    document.querySelectorAll(".policy-filter .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        document.querySelectorAll(".policy-filter .chip")
          .forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        policyOnlyLearned = chip.dataset.onlyLearned === "1";
        refreshPolicy();
      });
    });

    // 控制指令
    $("btn-start").addEventListener("click", () => {
      const floors = ($("waypoint-input").value || "")
        .split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean);
      sendCommand("start_inspection", {
        floors: floors.length ? floors : ["B2", "B1", "1F", "2F", "3F", "4F", "5F"],
      });
    });
    $("btn-pause").addEventListener("click", () => sendCommand("pause"));
    $("btn-resume").addEventListener("click", () => sendCommand("resume"));
    $("btn-stop").addEventListener("click", () => sendCommand("stop_inspection"));
    $("btn-reset").addEventListener("click", () => sendCommand("reset_fsm"));

    tickClock();
    startFpsCounter();
    connectRosbridge();

    // 除錯用：可在主控台呼叫 monitor.applyImage({data: "..."})
    window.monitor = { refreshStatus, refreshLogs, refreshFloors, refreshPolicy, applyImage };
  });
})();