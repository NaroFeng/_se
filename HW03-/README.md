# HW3 — SynapseBrain：個人情境編譯器與本機記憶圖譜

> 現代軟體工程 · HW3 · 以 SQLite 知識圖譜 + 本機 Ollama 打造「聊天即學習」的可攜式個人記憶系統

🔙 [回首頁](../)

## 一、作業概述

本作業實作 **SynapseBrain** — 一套單使用者、純本機的個人知識圖譜系統。

它要解決的問題很具體：**每一個 LLM 都是失憶的**。使用者希望「Claude / Gemini / ChatGPT」
知道自己正在做什麼、擅長什麼、哪些限制不能犯，卻又不想每次都手貼一大段系統提示。

SynapseBrain 把這件事拆成三段閉環：

| 階段 | 做法 | 對應模組 |
|---|---|---|
| **① 圖譜（Graph）** | 把「我在學 Docker」「我偏好 Python」「這是公司的硬性規則」拆成帶權重的**節點**與有語意的**邊**，存在本機 SQLite | `database.py` |
| **② 編譯（Compile）** | 把權重最高的 N 個節點**編譯**成一段可直接貼給外部 AI 的系統提示；這是「情境編譯器」——記憶不是塞給模型，而是編譯成模型看得懂的文字 | `compiler.py` |
| **③ 回寫（Ingest）** | 外部 AI 回覆時順帶吐出一段 `brain-update` JSON，把它解析回圖譜。於是「跟 AI 聊天」本身就變成「大腦生長」的方式 | `compiler.py` + `database.py` |

在這個閉環之外，本機還能直接跑 Ollama 聊天：對話結束後系統會自動做一次**記憶萃取**，
把值得留下的一句話寫回圖譜，使用者完全不需要手動敲任何指令。

| 項目 | 內容 |
|---|---|
| 作業主題 | 知識圖譜建模 + LLM 記憶系統設計 + 事件驅動權重衰減 |
| 核心技術 | FastAPI / SQLite3 / Ollama（`llama3:8b`）/ SSE 串流 / 原生 ES modules + force-graph |
| 前端 | 零建置（no build step），`<script type="module">` 直接跑，不需要 `npm` |
| 測試技術 | pytest / FastAPI TestClient（httpx）/ `tmp_path` 沙盒隔離 |
| 專案規模 | 3 個後端模組、4 個靜態檔案、2 張資料表、38 個測試函式 |

---

## 二、學習目標

- 理解 **「記憶不是塞給模型，而是編譯給模型」**：把非結構化知識圖譜轉成有優先順序、
  有長度上限、有約束條款的系統提示
- 練習 **LLM 輸出不可信** 的防禦性解析：8B 小模型不會照格式產出 fenced block，
  解析器必須同時應對「自訂標籤、裸 JSON、帶前置廢話、無關 code fence」四種真實輸出
- 設計 **事件驅動的權重衰減**（event-driven decay）：讓「最近沒用到」的知識自然淡出，
  而不是靠時間戳硬排序；同時讓「人格」與「規則」永不衰減
- 熟悉 **SSE 串流 + best-effort 後處理**：記憶萃取是附加價值，它失敗或逾時
  **不能**影響使用者已經收到的回覆
- 體會 **動態埠與單一真相來源**：把實際綁到的 port 寫進 `.port` 檔，
  讓腳本與自動化測試不必靠猜
- 練習 **SQLite 外鍵串聯刪除** 與自我修復式 schema 初始化（連線時自動確保資料表存在）

---

## 三、檔案結構

```text
HW03-/
├── README.md                    # 本檔案（HW 層級說明）
└── synapse-brain/
    ├── main.py                  # FastAPI 伺服器、路由、動態埠、Ollama 整合、SSE、記憶萃取
    ├── database.py              # SQLite helpers（nodes / edges CRUD、權重衰減、圖查詢）
    ├── compiler.py              # compile_prompt + brain-update 解析引擎
    ├── static/
    │   ├── index.html           # 三頁籤介面：編譯 Prompt / 匯入同步 / 聊天指令
    │   ├── app.js               # 原生 ES module，畫力導向圖 + 呼叫 /api/*
    │   ├── style.css            # 深色介面樣式
    │   └── force-graph.min.js   # 本地力導向圖函式庫（不依賴 CDN，遺失時才退回 CDN）
    ├── tests/
    │   ├── __init__.py
    │   └── test_brain.py        # 38 個測試函式
    ├── requirements.txt
    └── README.md                # 專案層級詳細說明（安裝、API、串流、錯誤分類）
```

### 3.1 資料表 Schema

```sql
CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    category   TEXT DEFAULT 'topic',   -- topic | skill | persona | rule
    weight     REAL DEFAULT 1.0,       -- 權重，夾在 [0.1, 10.0]
    summary    TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edges (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source   TEXT NOT NULL,
    target   TEXT NOT NULL,
    relation TEXT DEFAULT 'related_to',
    strength REAL DEFAULT 1.0,
    FOREIGN KEY(source) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target) REFERENCES nodes(id) ON DELETE CASCADE,
    UNIQUE(source, target, relation)
);
```

`PRAGMA foreign_keys = ON` 每次連線都會開啟，所以刪除節點時相鄰的邊會**自動串聯刪除**，
不會留下孤兒邊。

### 3.2 節點分類

| 類別 | 意義 | 是否參與衰減 |
|---|---|---|
| `topic` | 正在進行或關注的主題 | ✅ 會 |
| `skill` | 技能與工具能力 | ✅ 會 |
| `persona` | 穩定的人格特質 | ❌ 不會 |
| `rule` | 硬性規則與限制 | ❌ 不會 |

分類以外的字串一律落到 `topic`；`persona` 與 `rule` 被排除在衰減之外，
是因為**核心人設與硬約束不該因為最近沒提到就淡出**。

---

## 四、核心設計

### 4.1 編譯器：把圖譜變成系統提示

`compile_prompt(nodes, edges, focus_topic, limit)` 的流程：

1. 依 `weight` 由高到低排序。
2. 若指定 `focus_topic`，把該節點與它的 **1-hop 鄰居**「釘選」在清單最前面
   （鄰居之間仍依權重排序）。
3. 合併去重後截斷到 `limit`（預設 8，上限 50）。
4. 只保留**兩端都在選中集合內**的邊，避免 prompt 出現指向未宣告節點的關聯。
5. 組出四段式提示：記憶節點清單 → 已知關聯 → 約束條款 → **Ingestion Protocol**。

最後一段是整個閉環的關鍵：prompt 會明確要求模型在回覆**最後**附上一段
` ```brain-update ` fenced block，內含 `new_nodes` / `boost_nodes` / `new_edges`。
外部 AI 只要照做，使用者把回覆貼回「匯入同步」分頁，圖譜就會長大。

```text
# SynapseBrain — Compiled Context Prompt
## Active Memory Nodes (sorted by weight)
## Known Relations
## Constraint Instructions
## Ingestion Protocol (IMPORTANT)
```

### 4.2 防禦性解析：模型不會照格式

真實的 8B 模型會吐出這些形狀：

````text
format="json"  -> {"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}

```json
{"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}
```

Here is the brain update code block:
```
{"new_nodes": [...], "boost_nodes": [...], "new_edges": [...]}
```
````

因此 `extract_brain_updates()` **不去相信標籤**，而是：

- 掃描**所有** fenced block，只對標籤屬於 `{空, json, brain-update, brainupdate, brain_update}` 的候選解析；
- 另外**掃描整段回應**，處理 Ollama `format: "json"` 模式產生的裸 JSON；
- 候選必須能 `json.loads` 成物件，且帶有 `new_nodes` / `boost_nodes` / `new_edges`
  其中之一、且其值型別為 `list`（否則程式碼裡剛好出現 `{"new_nodes": "..."}` 就會被誤吞）；
- 以 payload 正規化後的 JSON 做去重，避免同一份內容被 fenced 與整段各抓到一次而寫入兩遍。

**解析不到時伺服器會把模型原始輸出印到終端機**——「沒有錯誤，但沒有新節點」
永遠是可診斷的，不會變成一句無言的靜默。

### 4.3 記憶萃取：讓「聊天」變成「學習」

本機聊天有兩條路徑（`/api/local-chat` 與 `/api/local-chat-stream`），
兩者都接受 `remember`（預設 `true`）。回覆結束後，系統會再跑一次 LLM，
這次只要求它輸出上面那個 `brain-update` JSON，然後把結果寫回圖譜。

這段萃取是 **best-effort**：

- 跑在**自己的 task**、有自己的 timeout（`EXTRACT_TIMEOUT`，預設 180 秒）；
- 有自己的 token 上限（`EXTRACT_MAX_TOKENS`，預設 400，因為只需要一個小 JSON）；
- 失敗或逾時**只會寫進 `memory.error`**，絕對不會中斷串流或丟掉使用者已收到的回覆。

串流期間會定期送 `{"busy": "正在整理記憶…"}` 與 keepalive frame，
避免中間那長達一分鐘的沉默被連線中間設備切斷。

| `memory.error` 含有 | 意義 |
|---|---|
| `（unreachable）` | Ollama 沒啟動或連不上 |
| `（timeout）` | Ollama 有起來，但這次太慢，超過 `EXTRACT_TIMEOUT` |
| `（model_missing）` | Ollama 有起來，但 `OLLAMA_MODEL` 還沒 `pull` 下来 |

### 4.4 事件驅動衰減（Event-driven decay）

**每當有節點被加權**（手動按「+ 加權」，或聊天萃取時回寫），
其他 `topic` / `skill` 節點的權重就乘上 `0.98`，下限 0.1。

三個刻意的設計：

| 決策 | 理由 |
|---|---|
| 只在「事件發生時」衰減，不是排程器定時掃 | 沒有背景執行緒、沒有計時器、沒有資源空轉 |
| 只衰減 `topic` / `skill` | `persona` / `rule` 是核心人設與硬約束，不該淡出 |
| 一次對話只衰減**一次**，不是每次加權都衰減 | `apply_ingest(..., decay_fn=...)` 讓衰減由呼叫端決定時機，避免一次匯入多個節點時權重被連乘砍到底 |

---

## 五、API 規格

互動式文件：啟動後開 `http://127.0.0.1:<port>/docs`（`<port>` 見 `.port` 檔）。

| 方法 | 端點 | Body | 說明 |
|---|---|---|---|
| GET | `/api/health` | — | 狀態 + Ollama 可達性 / 模型是否存在 |
| GET | `/api/graph` | — | `{ nodes, edges }`，供前端畫力導向圖 |
| POST | `/api/nodes` | `{id, label?, category?, weight?, summary?}` | 新增／更新節點（upsert） |
| POST | `/api/nodes/:id/boost` | `?amount=0.5` | 加權（夾在 0.1–10），並觸發其他節點衰減 |
| DELETE | `/api/nodes/:id` | — | 刪除節點 + 相鄰邊 |
| POST | `/api/edges` | `{source, target, relation?, strength?}` | 連線兩個節點 |
| POST | `/api/seed-demo` | — | 寫入範例圖譜（冪等合併） |
| POST | `/api/local-chat` | `{message, remember?}` | 代理 Ollama `/api/generate`（連不上則回示範回覆） |
| POST | `/api/local-chat-stream` | `{message, remember?}` | SSE token 串流；最後一帧帶 `memory` |
| POST | `/api/compile-prompt` | `{focus_topic?, limit?}` | 產生外部 AI 用的系統提示 |
| POST | `/api/ingest` | `{text}` | 解析 `brain-update` 區塊並套用到 SQLite |

### 5.1 串流幀格式

| Frame | 意義 |
|---|---|
| `{"token": "..."}` | 回覆的一段 token |
| `{"busy": "正在整理記憶…"}` | 回覆已完成，記憶萃取仍在跑 |
| `{"done": true, "memory": {...}}` | 最後一幀；`memory` 帶回寫結果（`blocks_found` / `new_nodes` / `boosted_nodes` / `decayed_nodes` / `errors`） |

### 5.2 匯入 payload 格式

```json
{
  "new_nodes": [{"id": "docker", "label": "Docker", "summary": "...", "weight": 1.0}],
  "boost_nodes": ["python"],
  "new_edges": [{"source": "docker", "target": "python", "relation": "relates_to"}]
}
```

格式錯誤的區塊會被跳過並回報在 `errors`，**不會中斷其餘部分的同步**。

---

## 六、使用方式

### 6.1 安裝與啟動

```powershell
cd HW03-/synapse-brain
pip install -r requirements.txt
python main.py
```

瀏覽 `http://127.0.0.1:8800`（實際埠號見啟動訊息或 `.port` 檔）。

### 6.2 動態埠

伺服器從 **8800** 開始往後掃到 **8820**，綁第一個空閒的 port，
所以不會跟 Ollama（11434）、Docker 或 WSL 的 port relay 打架。
實際綁到的 port 會寫進本目錄的 `.port` 檔，腳本與 CI 不必猜：

```powershell
python main.py
# [synapse] SynapseBrain 啟動於 http://127.0.0.1:8800  (port 記錄於 .port)

$port = Get-Content .port
Invoke-RestMethod "http://127.0.0.1:$port/api/graph"
```

起始點可用 `$env:SYNAPSE_PORT` 覆寫（例如 `$env:SYNAPSE_PORT=9000`）；
非數字會退回 `8800`。`.port` 與 `synapse.db` 皆已 git-ignore。

### 6.3 環境變數

| 變數 | 預設 | 用途 |
|---|---|---|
| `SYNAPSE_PORT` | `8800` | 起始 port，被占用就往後遞增（最多 +20） |
| `SYNAPSE_DB` | `./synapse.db` | SQLite 檔案路徑 |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `OLLAMA_MODEL` | `llama3:8b` | 模型標籤 |
| `OLLAMA_AUTOSTART` | `1` | 啟動時若連不上就自動 `ollama serve` |
| `OLLAMA_AUTOPULL` | `0` | 模型缺了就背景自動 pull |
| `OLLAMA_UNLOAD_AFTER_CHAT` | `0` | 每次聊天後把模型從 RAM 卸載 |
| `OLLAMA_TEMPERATURE` | `0.3` | 抽樣溫度 |
| `CHAT_MEMORY_LIMIT` | `8` | 注入每次系統提示的節點數 |
| `EXTRACT_TIMEOUT` | `180` | 記憶萃取允許的秒數 |
| `EXTRACT_MAX_TOKENS` | `400` | 萃取階段的 token 上限 |
| `EXTRACT_KEEPALIVE` | `10` | 萃取期間送 `busy` 幀的間隔秒數 |

### 6.4 本機模型（Ollama）

```powershell
ollama serve
ollama pull llama3:8b
# $env:OLLAMA_MODEL="qwen2.5:7b"   # 換模型
```

Ollama 連不上時不會讓整個系統壞掉，而是回一則示範回覆並在 `memory.error` 標註
`（unreachable）`。

> **本機模型很慢。** CPU 上跑 `llama3:8b`，一個聊天回合約 160 秒，
> 萃取階段再約 90–160 秒。等太久就換小一點的模型
> （`$env:OLLAMA_MODEL="qwen2.5:1.5b"`）。

### 6.5 介面操作

介面右側分三個頁籤：

| 頁籤 | 用法 |
|---|---|
| **編譯 Prompt** | 選焦點節點（不選＝整顆大腦）→ 設節點數上限 → 產生系統提示 → 複製貼給 Gemini / Claude |
| **匯入同步** | 把外部 AI 的回覆整段貼進來 → *同步到大腦* → 畫布即時更新 |
| **聊天 / 指令** | 直接打字聊天，或用斜線指令操作圖譜 |

斜線指令（前端解析，直接呼叫 API）：

| 指令 | 作用 | 範例 |
|---|---|---|
| `/add <id> <分類> <摘要…>` | 新增節點 | `/add docker skill 容器技術` |
| `/boost <id>` | 幫節點加權 | `/boost python` |
| `/connect <來源> <目標> <關係>` | 連線兩個節點 | `/connect fastapi python depends_on` |

其他文字會送給本機 Ollama，並自動帶入權重最高的記憶節點。

---

## 七、測試

```powershell
cd HW03-/synapse-brain
pytest -v
```

38 個測試函式，涵蓋四個面向：

| 面向 | 代表案例 |
|---|---|
| **圖譜 CRUD** | `test_node_crud_and_boost`、`test_edge_crud_and_cascade`（外鍵串聯刪除） |
| **編譯器** | `test_compile_prompt_selects_top_weights`、`test_compile_prompt_focus_pins_neighbours`（焦點節點與鄰居被釘選） |
| **Ingest 解析** | `test_ingest_valid_block`、`test_ingest_tolerates_models_that_drop_the_fence_tag`、`test_ingest_ignores_unrelated_code_fences`、`test_bare_and_fenced_forms_do_not_double_count`（裸 JSON 不重複計數） |
| **衰減語意** | `test_decay_only_hits_topic_and_skill`、`test_decay_repeats_and_never_below_floor`、`test_ingest_calls_decay_once_with_touched_ids` |
| **串流與容錯** | `test_stream_survives_extraction_failure`、`test_stream_emits_keepalive_during_extraction`、`test_extract_memory_never_raises`、`test_timeout_is_not_misreported_as_unreachable` |
| **埠與環境** | `test_resolve_port_skips_occupied`、`test_port_file_roundtrip`、`test_unload_after_chat_flag` |

**零副作用**：測試一律使用 `tmp_path` 沙盒資料庫（`SYNAPSE_DB` 指向沙盒），
不會寫到正式的 `synapse.db`。

### 7.1 手動 E2E

新增 `python` + `fastapi` 兩個節點 → 連上 `fastapi —depends_on→ python`
→ 按 *產生外部 Prompt* → 把一段帶 `brain-update` 的回覆貼進 *Ingest → Sync to Brain*
→ 畫布即時更新。

### 7.2 對線上伺服器做 smoke test

```powershell
$port = Get-Content .port
curl.exe "http://127.0.0.1:$port/api/graph"
curl.exe -X POST "http://127.0.0.1:$port/api/compile-prompt" -H "Content-Type: application/json" -d '{"limit": 3}'
```

---

## 八、設計取舍（奧卡姆剃刀）

| 決策 | 理由 |
|---|---|
| SQLite 而非向量資料庫 | 知識量是「一人份」，需要的是**可解釋的權重排序**而非語意相似度檢索 |
| 前端零建置（ES modules 直跑） | 沒有 `npm`，就沒有 build 壞掉的那一天 |
| 力導向圖函式庫**本地內嵌** + CDN 備援 | 離線環境也能開圖；檔案遺失才退回 CDN |
| 提示詞編譯而不是塞整個 DB | 每次只給 `limit` 個節點，token 有上限，輸出才聚焦 |
| 衰減由「事件」觸發而非排程器 | 沒有背景執行緒、沒有資源空轉，邏輯單純可測 |
| 萃取獨立 task + 獨立 timeout | 附加功能失敗不能影響主要功能——這是可靠性底線 |
| `compiler.py` 只 import 標準函式庫 | 資料寫入用 `upsert_node_fn` 注入，不 import `database.py`、也不 import `main.py`，避免循環相依，單元測試不必啟動伺服器 |
| 埠寫入 `.port` 檔 | 讓腳本與 CI 讀檔就好，不用解析 log 或硬編碼 |
| 自我修復式 schema 初始化 | 連線時自動 `executescript(SCHEMA)`，避免 DB 被換掉之後整個 API 500 |
| 指令一律 `python -m pytest` | 避免多版本 Python 的套件版本衝突，貼到任何環境都跑得動 |

---

## 九、延伸與參考

### 後續可改進

- **多使用者與權限**：目前是單使用者本機應用，可加帳號層與 per-user 圖譜
- **向量檢索**：為 `summary` 加 embedding，讓「相關但不常用」的節點也能被召回
- **時間軸檢視**：把 `updated_at` 畫成節點新舊的視覺線索
- **匯入 / 匯出**：支援 Markdown 或 JSON 格式的大腦備份與遷移
- **更大的萃取模型**：`EXTRACT_MAX_TOKENS` 與 `OLLAMA_MODEL` 分開設定，萃取可以用小模型加速

### 參考資源

- [FastAPI 官方教學](https://fastapi.tiangolo.com/tutorial/)
- [Testing FastAPI](https://fastapi.tiangolo.com/tutorial/testing/)
- [SQLite 官方文件](https://sqlite.org/docs.html)
- [Ollama 官方文件](https://github.com/ollama/ollama)
- [pytest 官方文件](https://docs.pytest.org/)
- [vasturiano/force-graph](https://github.com/vasturiano/force-graph)

---

## 共用樣式 (../assets/style.css)

建立本作業的 index.html 時,引用根目錄共用樣式:

`html
<link rel="stylesheet" href="../assets/style.css">
`

### 設計 token (CSS 變數)

| 變數 | 用途 |
|---|---|
| --bg --bg-elev --bg-code | 三層背景 |
| --text --text-muted | 文字主色 / 次色 |
| --border | 邊框 / 分隔線 |
| --accent --accent-hover | 主題藍 (淺 / 深) |
| --v1 --v2 --v3 | 版本色 (琥珀 / 綠 / 紫) |
| --shadow --shadow-lg | 陰影 |
| --radius --max-w | 圓角 / 內容最大寬 |
| --mono --sans | 等寬字 / 系統字 |

### 主題切換

在 <html> 加 class="dark" 進入暗模式;切換按鈕 + localStorage 邏輯見根目錄 index.html 內 <script>。

### 元件 class

| 類別 | 用途 |
|---|---|
| .nav .nav-inner .brand .nav-links .theme-toggle | 頂部導覽列 (sticky) |
| .hero .hero-inner .eyebrow .subtitle .hero-actions | Hero 區塊 |
| .btn .btn.primary .btn.ghost | 按鈕 (三種) |
| .section .lead h2 h3 | 內容區段與標題 |
| .hw-grid .hw-card .hw-card.done .hw-card.current | 卡片網格 |
| .hw-num .hw-title .hw-desc .hw-status .dot | 卡片內欄位 |
| .info-table .info-row .info-label | 資訊表格 |
| .footer .footer-meta | 頁尾 |
| code p code li code | 程式碼行內樣式 |

### 響應式

RWD breakpoint: 720px。在此寬度以下,.nav-inner 換行、.hero / .section 縮減 padding、.info-row 改為單欄。
