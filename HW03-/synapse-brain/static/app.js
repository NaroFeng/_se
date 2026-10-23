/* SynapseBrain 前端：圖譜繪製 + 頁籤 + API 呼叫 */
const api = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}：HTTP ${r.status}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `${path}：HTTP ${r.status}`);
    return data;
  },
  async del(path) {
    const r = await fetch(path, { method: "DELETE" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `${path}：HTTP ${r.status}`);
    return data;
  },
};

const CATEGORY_COLORS = {
  topic: "#5aa2ff",
  skill: "#43d39a",
  persona: "#b78cff",
  rule: "#ffb454",
};

const RELATION_COLORS = {
  depends_on: "#5aa2ff",
  part_of: "#43d39a",
  relates_to: "#46587e",
};

function nodeRadius(node) {
  const base = Math.sqrt(Math.max(1, Number(node.val || node.weight || 1))) * 3 + 4;
  return base * (node.pscale || 1); // 星球模式：中心大、衛星小
}

function toForceData(pinned = true) {
  roles = computeRoles();
  return {
    nodes: graph.nodes.map((n) => ({
      ...n,
      val: Math.max(1, Number(n.weight) || 1),
      color: CATEGORY_COLORS[n.category] || CATEGORY_COLORS.topic,
      // 主節點原尺寸，衛星小一號，孤立節點居中
      pscale: roles.isHub(n.id) ? 1.0 : roles.parentOf.has(n.id) ? 0.75 : 0.9,
    })),
    links: graph.edges.map((e) => ({ ...e })),
  };
}

function endId(x) {
  return x && typeof x === "object" ? x.id : x;
}

// 主節點 vs 衛星：連接數≥2 或權重夠大＝主節點；只有一條主關聯＝衛星
function computeRoles() {
  const deg = new Map();
  const adj = new Map();
  for (const e of graph.edges) {
    if (!e.source || !e.target || e.source === e.target) continue;
    deg.set(e.source, (deg.get(e.source) || 0) + 1);
    deg.set(e.target, (deg.get(e.target) || 0) + 1);
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  }
  const w = new Map(graph.nodes.map((n) => [n.id, Number(n.weight) || 0]));
  const isHub = (id) => (deg.get(id) || 0) >= 2 || (w.get(id) || 0) >= 2.5;
  const parentOf = new Map();
  for (const n of graph.nodes) {
    if ((deg.get(n.id) || 0) !== 1 || isHub(n.id)) continue;
    const nb = (adj.get(n.id) || [])[0];
    if (!nb) continue;
    const nbLeaf = (deg.get(nb) || 0) === 1 && !isHub(nb);
    if (!nbLeaf) parentOf.set(n.id, nb); // 兩點孤島就各走各的，不硬湊
  }
  return { isHub, parentOf };
}

function isSatelliteLink(l) {
  if (!roles) return false;
  return roles.parentOf.has(endId(l.source)) || roles.parentOf.has(endId(l.target));
}

/* 星球模式已退役：改為主節點＋衛星自動判定（見 computeRoles）。 */

function paintNode(node, ctx, globalScale) {
  const r = nodeRadius(node);
  const dimmed = hlNodes && !hlNodes.has(node.id);
  const alpha = dimmed ? 0.12 : 1;
  const labelColor = dimmed ? "rgba(147,160,184,0.6)" : "#e8edf7";
  ctx.save();
  if (alpha < 1) ctx.globalAlpha = alpha;
  // 光暈（真正的霓虹輝光）
  ctx.shadowColor = node.color;
  ctx.shadowBlur = 22;
  ctx.fillStyle = node.color;
  ctx.beginPath();
  ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
  ctx.fill();
  // 亮核
  ctx.shadowBlur = 0;
  ctx.fillStyle = "rgba(255,255,255,0.9)";
  ctx.beginPath();
  ctx.arc(node.x, node.y, Math.max(1.5, r * 0.32), 0, 2 * Math.PI, false);
  ctx.fill();
  // 選中光環
  if (selectedId === node.id) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(node.x, node.y, r + 5, 0, 2 * Math.PI, false);
    ctx.stroke();
  }
  // 標籤（黑底描邊浮字）
  const fontSize = Math.max(2.5, 11 / globalScale);
  ctx.font = `${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const ly = node.y + r + 4 / globalScale;
  ctx.lineWidth = 3;
  ctx.strokeStyle = "rgba(10,14,25,0.9)";
  const label = node.label || node.id;
  ctx.strokeText(label, node.x, ly);
  ctx.fillStyle = labelColor;
  ctx.fillText(label, node.x, ly);
  ctx.restore();
}

function paintHitArea(node, color, ctx) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(node.x, node.y, nodeRadius(node) + 8, 0, 2 * Math.PI, false);
  ctx.fill();
}

const CATEGORY_LABELS = {
  topic: "主題",
  skill: "技能",
  persona: "人格",
  rule: "規則",
};

const catLabel = (c) => CATEGORY_LABELS[c] || c || "主題";

let graph = { nodes: [], edges: [] };
let Graph = null; // force-graph 實例（2D 力導向）
let hlNodes = null; // 懸停高亮的節點 id 集合（null＝全部正常顯示）
let pendingFit = false; // 資料更新後，等引擎停穩再自動對焦
let roles = null; // { isHub(id), parentOf }：主節點 vs 衛星（每次 render 重算）
let selectedId = null;

const $ = (id) => document.getElementById(id);

function showCanvasError(msg) {
  const el = $("canvas-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

function clearCanvasError() {
  $("canvas-error").classList.add("hidden");
}

/* 舊 vis-network 的 toVisNodes/toVisEdges 已退役，改用上面的 toForceData＋paintNode。 */

function sizeGraph(retries = 6) {
  if (!Graph) return;
  const box = $("network");
  const w = box.clientWidth, h = box.clientHeight;
  if ((w < 50 || h < 50) && retries > 0) {
    setTimeout(() => sizeGraph(retries - 1), 200); // 版面還沒撐開就晚點再量
    return;
  }
  Graph.width(Math.max(w, 50)).height(Math.max(h, 50));
}

function ensureGraph() {
  if (typeof ForceGraph === "undefined") {
    showCanvasError("圖譜函式庫載入失敗（本地與 CDN 都連不上）。請確認網路連線後重新整理頁面。");
    return false;
  }
  clearCanvasError();
  if (Graph) return true;
  try {
    Graph = ForceGraph()($("network"))
      .graphData(toForceData())
      .nodeVal("val")
      .nodeColor((n) => n.color)
      .nodeLabel((n) => `${n.label || n.id}（${catLabel(n.category)}，權重 ${Number(n.weight).toFixed(1)}）<br>${n.summary || ""}`)
      .nodeCanvasObject(paintNode)
      .nodeCanvasObjectMode(() => "replace")
      .nodePointerAreaPaint(paintHitArea)
      .linkColor((l) => RELATION_COLORS[l.relation] || "#46587e")
      .linkWidth((l) => Math.min(3, 0.6 + Number(l.strength || 1) * 0.7))
      .linkDirectionalParticles((l) => (l.relation === "depends_on" ? 3 : 1))
      .linkDirectionalParticleSpeed(0.004)
      .linkDirectionalParticleWidth(2)
      .linkDirectionalParticleColor(() => "rgba(200,225,255,0.8)")
      .warmupTicks(60)
      .cooldownTicks(120)
      .onNodeClick((node) => {
        if (node) {
          selectNode(node.id);
          if (Graph.refresh) Graph.refresh();
        }
      })
      .onBackgroundClick(() => hideCard())
      .onNodeHover((node) => {
        $("network").style.cursor = node ? "pointer" : "";
        if (!node) {
          hlNodes = null;
        } else {
          hlNodes = new Set([node.id]);
          for (const e of graph.edges) {
            if (e.source === node.id) hlNodes.add(e.target);
            else if (e.target === node.id) hlNodes.add(e.source);
          }
        }
        if (Graph.refresh) Graph.refresh();
      });
    sizeGraph();
    // 引擎停穩（佈局完成）才對焦；平常拖曳不會觸發亂跳
    Graph.onEngineStop(() => {
      if (!pendingFit) return;
      pendingFit = false;
      sizeGraph();
      try { Graph.zoomToFit(600); } catch (e) { /* ignore */ }
    });
    window.addEventListener("resize", sizeGraph);
    // 主節點互吸＋衛星緊吸附：衛星鏈又短又緊，主節點鏈鬆一點
    try {
      Graph.d3AlphaDecay(0.025);
      Graph.d3VelocityDecay(0.35);
      const linkF = Graph.d3Force("link");
      if (linkF) {
        if (linkF.distance) linkF.distance((l) => (isSatelliteLink(l) ? 48 : 110));
        if (linkF.strength) linkF.strength((l) => (isSatelliteLink(l) ? 1.1 : 0.6));
      }
      const chargeF = Graph.d3Force("charge");
      if (chargeF && chargeF.strength) chargeF.strength(-90);
    } catch (e) { /* 舊版相容，忽略 */ }
  } catch (e) {
    showCanvasError(`圖譜繪製失敗：${e.message}。請按 Ctrl+F5 重新整理；若仍失敗請把這段文字貼給我。`);
    return false;
  }
  return true;
}

function renderGraph() {
  if (!ensureGraph()) return;
  sizeGraph();
  try {
    Graph.linkCurvature(0.15); // 輕微弧度：有機感但不花俏
    Graph.graphData(toForceData());
    pendingFit = true; // 對焦等引擎停穩後再做，避免對到未散開的佈局
  } catch (e) {
    showCanvasError(`圖譜更新失敗：${e.message}`);
    return;
  }
  // 保險：2.5 秒後若還沒對到，強制對焦一次
  setTimeout(() => {
    if (pendingFit && Graph) {
      pendingFit = false;
      sizeGraph();
      try { Graph.zoomToFit(600); } catch (e) { /* ignore */ }
    }
  }, 2500);
  // 自我檢查：真的有畫出 canvas 嗎？
  setTimeout(() => {
    const box = $("network");
    const w = box.clientWidth, h = box.clientHeight;
    if (!box.querySelector("canvas")) {
      showCanvasError(
        `資料有載入（${graph.nodes.length} 個節點），但畫布沒有畫出來（畫布尺寸 ${w}x${h}）。\n` +
        `請依序試：① 按 Ctrl+F5 強制重新整理 ② 換 Chrome/Edge 開 ③ 按 F12 開主控台把紅字貼給我。`
      );
    }
  }, 1500);
  if (graph.nodes.length === 0) {
    $("graph-stats").textContent = "目前沒有節點 — 到「聊天 / 指令」頁籤用 /add 新增第一個節點吧！";
  } else {
    const hubs = graph.nodes.filter((n) => roles && roles.isHub(n.id)).length;
    const sats = roles ? roles.parentOf.size : 0;
    $("graph-stats").textContent = `${graph.nodes.length} 個節點 · ${graph.edges.length} 條連線（主節點 ${hubs} · 衛星 ${sats}，滾輪縮放、拖曳平移）`;
  }
  refreshFocusOptions();
}

function refreshFocusOptions() {
  const sel = $("focus-select");
  const cur = sel.value;
  sel.innerHTML = '<option value="">— 整顆大腦 —</option>';
  for (const n of [...graph.nodes].sort((a, b) => b.weight - a.weight)) {
    const o = document.createElement("option");
    o.value = n.id;
    o.textContent = `${n.label || n.id}（權重 ${Number(n.weight).toFixed(1)}）`;
    sel.appendChild(o);
  }
  sel.value = cur;
}

function selectNode(id) {
  selectedId = id;
  const n = graph.nodes.find((x) => x.id === id);
  if (!n) return hideCard();
  $("node-card").classList.remove("hidden");
  $("node-title").textContent = `${n.label || n.id}`;
  $("node-meta").textContent = `id：${n.id} · ${catLabel(n.category)} · 權重 ${Number(n.weight).toFixed(1)}`;
  $("node-summary").textContent = n.summary || "（尚無摘要）";
}

function hideCard() {
  selectedId = null;
  $("node-card").classList.add("hidden");
}

async function reload() {
  try {
    graph = await api.get("/api/graph");
  } catch (e) {
    showCanvasError(backendUnreachableHint(e));
    logChat("大腦", `圖譜載入失敗：${e.message}`);
    return;
  }
  clearCanvasError();
  renderGraph();
  if (selectedId) selectNode(selectedId);
}

function logChat(who, text) {
  const div = document.createElement("div");
  div.className = "chat-msg" + (who === "你" ? " me" : "");
  div.textContent = `${who}：${text}`;
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
}

async function handleCommand(raw) {
  const parts = raw.trim().split(/\s+/);
  const cmd = parts[0].toLowerCase();
  if (cmd === "/add") {
    const [, id, category = "topic", ...rest] = parts;
    if (!id) throw new Error("用法：/add <id> <分類> <摘要…>，例如 /add docker skill 容器技術");
    return api.post("/api/nodes", { id, label: id, category, weight: 1.0, summary: rest.join(" ") });
  }
  if (cmd === "/boost") {
    const id = parts[1];
    if (!id) throw new Error("用法：/boost <id>，例如 /boost python");
    return api.post(`/api/nodes/${encodeURIComponent(id)}/boost`, {});
  }
  if (cmd === "/connect") {
    const [, source, target, relation = "related_to"] = parts;
    if (!source || !target) throw new Error("用法：/connect <來源> <目標> <關係>，例如 /connect fastapi python depends_on");
    return api.post("/api/edges", { source, target, relation });
  }
  return null; // 不是指令
}

async function refreshOllamaStatus() {
  const el = $("ollama-status");
  try {
    const h = await api.get("/api/health");
    const o = h.ollama || {};
    if (!o.reachable) {
      el.textContent = "本機模型：未連線（先用示範回覆；要啟用請安裝 Ollama，或確認它有跟著啟動）";
    } else if (o.pulling) {
      el.textContent = `本機模型：${o.model} 下載中…（稍後再試）`;
    } else if (!o.model_present) {
      el.textContent = `本機模型：已連線，但還沒下載 ${o.model}（請執行 ollama pull ${o.model}）`;
    } else {
      el.textContent = `本機模型：${o.model} 已就緒${o.managed ? "（由本程式自動啟動）" : ""}`;
    }
  } catch (e) {
    el.textContent = "本機模型：狀態未知";
  }
}

function initTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

function init() {
  initTabs();

  $("btn-refresh").addEventListener("click", () => {
    reload().catch((e) => alert(e.message));
    refreshOllamaStatus();
  });
  $("btn-demo").addEventListener("click", async () => {
    if (!confirm("載入範例圖譜？（11 個節點＋12 條連線，同 id 的節點會被覆寫）")) return;
    await api.post("/api/seed-demo", {});
    hideCard();
    await reload();
  });
  /* 主節點/衛星由連接數自動判定，無需手動設中心。 */

  $("btn-boost").addEventListener("click", async () => {
    if (!selectedId) return;
    await api.post(`/api/nodes/${encodeURIComponent(selectedId)}/boost`, {});
    await reload();
  });
  $("btn-delete").addEventListener("click", async () => {
    if (!selectedId || !confirm(`確定刪除節點「${selectedId}」嗎？`)) return;
    await api.del(`/api/nodes/${encodeURIComponent(selectedId)}`);
    hideCard();
    await reload();
  });

  $("btn-compile").addEventListener("click", async () => {
    try {
      const data = await api.post("/api/compile-prompt", {
        focus_topic: $("focus-select").value || null,
        limit: Number($("limit-input").value) || 8,
      });
      $("prompt-output").value = data.prompt;
    } catch (e) {
      $("prompt-output").value = `產生失敗：${e.message}`;
    }
  });
  $("btn-copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("prompt-output").value);
    $("btn-copy").textContent = "✓ 已複製！";
    setTimeout(() => ($("btn-copy").textContent = "⧉ 複製到剪貼簿"), 1500);
  });

  $("btn-ingest").addEventListener("click", async () => {
    try {
      const data = await api.post("/api/ingest", { text: $("ingest-input").value });
      graph = data.graph;
      renderGraph();
      const lines = [
        `找到 ${data.blocks_found} 個 brain-update 區塊`,
        `新增節點：${data.new_nodes.length ? data.new_nodes.join("、") : "無"}`,
        `加權節點：${data.boosted_nodes.length ? data.boosted_nodes.join("、") : "無"}`,
        `新增連線：${data.new_edges.length ? data.new_edges.join("、") : "無"}`,
      ];
      if (data.errors.length) lines.push(`注意：\n- ${data.errors.join("\n- ")}`);
      $("ingest-result").textContent = lines.join("\n");
    } catch (e) {
      $("ingest-result").textContent = `同步失敗：${e.message}`;
    }
  });

function showThinking(text) {
  hideThinking();
  const div = document.createElement("div");
  div.className = "chat-msg thinking";
  div.id = "chat-thinking";
  div.textContent = `大腦：${
    text || "思考中…（本機模型第一次回覆較慢，請稍等）"
  }`;
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
}

function hideThinking() {
  document.getElementById("chat-thinking")?.remove();
}

function startBrainMessage() {
  const div = document.createElement("div");
  div.className = "chat-msg";
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return div;
}

// port 由 server 動態挑選，所以一律從目前頁面推導，不寫死。
function serverOrigin() {
  return location.protocol.startsWith("http")
    ? location.origin
    : "http://127.0.0.1:8800";
}

function backendUnreachableHint(e) {
  return (
    `連不到後端（${e && e.message ? e.message : "network error"}）。` +
    `請確認：① python main.py 還在跑（看終端機最後一行印的 port）；` +
    `② 網址是 ${serverOrigin()}；` +
    `③ 若 server 重啟過並換了 port，請用它印出來的新網址重新開啟本頁。`
  );
}

async function streamChat(text, remember, onToken, onBusy) {
  let r;
  try {
    r = await fetch("/api/local-chat-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, remember }),
    });
  } catch (e) {
    // fetch 在「連不到 server」時只會丟 TypeError: Failed to fetch，完全沒有
    // 線索。把它換成真的能行動的訊息，不然使用者只會看到一個英文錯誤。
    throw new Error(backendUnreachableHint(e));
  }
  if (!r.ok) throw new Error(`/api/local-chat-stream：HTTP ${r.status}`);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let final = null;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!raw.startsWith("data:")) continue;
        let evt;
        try {
          evt = JSON.parse(raw.slice(5));
        } catch (e) {
          continue;
        }
        if (evt.token) onToken(evt.token);
        else if (evt.busy) {
          // 回覆已經出完、server 還在萃取記憶中。這段在本機模型上可能長達
          // 數十秒，沒有回饋的話畫面看起來就是當掉了。
          if (onBusy) onBusy(evt.busy);
        } else if (evt.done) final = evt;
      }
    }
  } catch (e) {
    throw new Error(`連線中斷（${e.message}）。${backendUnreachableHint(e)}`);
  }
  return final;
}

async function handleMemory(m) {
  if (!m) return;
  if (m.error) {
    logChat("大腦", m.error);
    return;
  }
  const newNodes = m.new_nodes || [];
  const boosted = m.boosted_nodes || [];
  const edges = m.new_edges || [];
  if (newNodes.length + boosted.length + edges.length === 0) return;
  const bits = [];
  if (newNodes.length) bits.push(`新增：${newNodes.join("、")}`);
  if (boosted.length) bits.push(`加權：${boosted.join("、")}`);
  if (edges.length) bits.push(`連線：${edges.join("、")}`);
  logChat("大腦", `已記住 — ${bits.join("；")}`);
  graph = m.graph || (await api.get("/api/graph"));
  renderGraph();
}

  let sending = false;
  const send = async () => {
    if (sending) return; // 上一輪還沒跑完：避免本機模型排隊卡死
    const input = $("chat-input");
    const text = input.value.trim();
    if (!text) return;
    sending = true;
    input.value = "";
    logChat("你", text);
    showThinking();
    try {
      if (text.startsWith("/")) {
        const res = await handleCommand(text);
        if (res) {
          logChat("大腦", `成功：${JSON.stringify(res)}`);
          await reload();
        } else {
          logChat("大腦", "未知指令，可用 /add、/boost、/connect（看下方指令說明）");
        }
      } else {
        const msgDiv = startBrainMessage();
        try {
          const final = await streamChat(
            text,
            $("chat-remember").checked,
            (tok) => {
              hideThinking(); // 第一個字到了就撤掉等待提示
              msgDiv.textContent += tok;
              $("chat-log").scrollTop = $("chat-log").scrollHeight;
            },
            (busy) => showThinking(busy) // 回覆出完但還在萃取記憶時的提示
          );
          if (!final) throw new Error("串流中斷，請重試");
          if (!msgDiv.textContent) {
            msgDiv.textContent = "（模型這次回傳空白，沒有內容。請再送一次看看。）";
          }
          await handleMemory(final.memory);
        } catch (e) {
          // 已經收到 token 的話絕對不要刪掉——那使用者辛苦等到的回覆就沒了。
          // 只在「一個字都沒收到」時才清掉空的 bubble。
          if (msgDiv.textContent) {
            msgDiv.classList.add("partial");
            logChat("大腦", `出錯：${e.message}`);
          } else {
            msgDiv.remove();
            logChat("大腦", `出錯：${e.message}`);
          }
        }
      }
    } catch (e) {
      logChat("大腦", `出錯：${e.message}`);
    } finally {
      hideThinking();
      sending = false;
    }
  };
  $("btn-send").addEventListener("click", send);
  $("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") send();
  });

  reload();
  refreshOllamaStatus();
  logChat("大腦", "哈囉！我是你的本地記憶小幫手。輸入 /add 新增節點，或直接跟我聊天（需開 Ollama，否則為示範回覆）。");
}

init();
