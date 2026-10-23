# 履歷問卷蒐集系統 (Resume Survey System)

極簡、可測試的履歷問卷蒐集系統。填表 → 驗證 → 上傳大頭照 → 寫入 SQLite → 卡片列表動態更新。

> 現代軟體工程 · HW6 · 以 FastAPI + SQLite3 + 原生前端，打造並以三層自動化測試完整護航的極簡 Web 系統

---

## 一、快速開始

```bash
cd resume-survey-app

# 安裝依賴
python -m pip install -r requirements.txt
python -m playwright install chromium      # 只有跑 E2E 測試時才需要

# 啟動服務
python -m uvicorn app.main:app --reload
```

| 網址 | 說明 |
|---|---|
| <http://127.0.0.1:8000/> | 履歷問卷填寫頁（表單 + 已提交卡片列表） |
| <http://127.0.0.1:8000/test-docs> | **測試架構與案例說明專頁** |
| <http://127.0.0.1:8000/docs> | Swagger UI（自動產生的 API 文件） |

---

## 二、檔案結構

```text
resume-survey-app/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI 進入點、路由與靜態檔案掛載
│   ├── database.py        # SQLite 連線與初始化表結構
│   └── validators.py      # 獨立的商業邏輯驗證函式 (供 Unit Test 測試)
├── static/
│   ├── index.html         # 履歷問卷填寫與已提交列表頁
│   └── test-docs.html     # 測試架構、邏輯與案例介紹專頁
├── uploads/               # 存放上傳的圖片 (需自動建立，加入 .gitkeep)
├── data/                  # 存放 SQLite 資料庫檔案 (resume.db)
├── tests/
│   ├── conftest.py        # Pytest fixtures (包含測試用 DB 與環境隔離)
│   ├── test_unit.py       # 單元測試
│   ├── test_api.py        # 系統/API 測試
│   └── test_e2e.py        # Playwright E2E 測試
└── requirements.txt
```

---

## 三、API 規格

| 方法 | 路徑 | 說明 | 回應 |
|---|---|---|---|
| `GET` | `/` | 履歷問卷填寫頁 | `static/index.html` |
| `GET` | `/test-docs` | 測試說明專頁（內含互動式測試控制台） | `static/test-docs.html` |
| `POST` | `/api/submissions` | 送出履歷問卷（multipart/form-data） | `201` + 該筆資料 JSON |
| `GET` | `/api/submissions` | 取得所有履歷問卷 | `200` + JSON 陣列 |
| `POST` | `/api/run-tests` | **開發者工具**：執行測試套件並回傳輸出 | `200` + 執行結果 JSON |

`POST /api/submissions` 欄位：`name`、`email`、`role`、`experience_years`、`bio`（選填）、`avatar`（檔案）。

驗證失敗回傳 `400 Bad Request`；必要欄位未提供回傳 `422`。

### `POST /api/run-tests`（開發者專用）

讓網頁上的按鈕可以直接執行測試。Request body：

```json
{ "suite": "unit" | "api" | "e2e" | "e2e_headed" | "all" }
```

| suite | 實際執行的指令 |
|---|---|
| `unit` | `python -m pytest -v --tb=short tests/test_unit.py` |
| `api` | `python -m pytest -v --tb=short tests/test_api.py` |
| `e2e` | `python -m pytest -v --tb=short tests/test_e2e.py` |
| `e2e_headed` | `python -m pytest -v --tb=short tests/test_e2e.py --headed --slowmo 500` |
| `all` | `python -m pytest -v --tb=short` |

回應欄位：`suite`、`command`、`returncode`、`passed`、`timed_out`、`duration_seconds`、`stdout`、`stderr`。

> ⚠️ 此端點會在專案根目錄啟動 pytest 子行程，屬於**開發工具**，正式環境請勿對外開放。
> 執行時子行程的 `RESUME_DB_PATH` / `RESUME_UPLOAD_DIR` 會被覆寫成一次性暫存資料夾，
> 且以 `RESUME_RUN_TESTS_ACTIVE` 標記以防止「測試再觸發測試」的無限遞迴。

---

## 四、資料表 Schema

```sql
CREATE TABLE submissions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    email            TEXT    NOT NULL,
    role             TEXT    NOT NULL,
    experience_years INTEGER NOT NULL,
    bio              TEXT,
    avatar_path      TEXT    NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 五、測試

```bash
# 三層一次跑完
pytest -v

# 分層執行
pytest tests/test_unit.py -v     # Layer 1：純函式，數毫秒
pytest tests/test_api.py  -v     # Layer 2：HTTP 契約，毫秒級
pytest tests/test_e2e.py  -v     # Layer 3：瀏覽器旅程，秒級
```

| 層級 | 測試檔 | 測試函式數 | 依賴 DB | 依賴網路 |
|---|---|---|---|---|
| Unit | `tests/test_unit.py` | 13 | 否 | 否 |
| Web API | `tests/test_api.py` | 21 | 是（沙盒 DB） | 否（in-process） |
| E2E | `tests/test_e2e.py` | 9 | 是（沙盒 DB） | 是（僅 localhost） |

完整案例對照表請見 <http://127.0.0.1:8000/test-docs>。

### 互動式測試控制台

`/test-docs` 頁面提供兩種貼心功能：

1. **Terminal 快速指令中心** — 6 個精確的 `python -m pytest` 指令，點一下即可複製到剪貼簿
   （含「有頭慢動作觀看 E2E 自動填表」與「開啟 Playwright Trace Viewer」）。
2. **網頁即時測試執行器** — 5 個按鈕直接在本頁執行測試，結果以模擬終端機完整呈現，
   並附綠燈／紅燈狀態徽章與總耗時。

### 測試隔離

測試**絕對不會**寫入正式的 `data/resume.db` 與 `uploads/`：

* API 測試透過 `tmp_path` fixture 取得專屬的沙盒資料庫與上傳目錄。
* E2E 測試在 `tmp_path_factory` 下啟動獨立 uvicorn 子行程，並以
  `RESUME_DB_PATH` / `RESUME_UPLOAD_DIR` 環境變數指向沙盒。
* `conftest.py` 在 `import app.main` **之前**設定環境變數，避免模組層級的
  `app = create_app()` 碰到正式路徑。
* 網頁執行器 `/api/run-tests` 另外再包一層：子行程的 DB 與上傳目錄會被導向
  `tempfile.TemporaryDirectory()`，執行完即刪除。

---

## 六、技術棧

| 層級 | 技術 |
|---|---|
| 前端 | HTML5 / Tailwind CSS (CDN) / 原生 JavaScript (Fetch API) |
| 後端 | Python 3.10+ / FastAPI / 原生 `sqlite3` |
| 測試 | pytest / httpx (TestClient) / Playwright (pytest-playwright) |

---

## License

本專案為課程作業，僅供學習與研究用途。
