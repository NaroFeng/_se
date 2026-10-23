# HW6 — 履歷問卷蒐集系統 (Resume Survey System)

> 現代軟體工程 · HW6 · 以 FastAPI + SQLite3 + 原生前端，打造並以「Unit / Web API / E2E」三層自動化測試完整護航的極簡 Web 系統

🔙 [回首頁](../)

## 一、作業概述

本作業實作一套 **履歷問卷蒐集系統**。使用者填寫姓名、Email、應徵職位、年資、簡歷並上傳大頭照，
系統會即時驗證格式、將圖片安全落地、把資料寫入 SQLite，並在前端卡片列表**動態更新**已提交的履歷。

作業的真正重點不在功能，而在於 **用三層自動化測試把每個邊界都釘死**，並用一個視覺化網頁把測試邏輯完整說清楚。

| 項目 | 內容 |
|---|---|
| 作業主題 | 極簡 Web 系統設計 + 三層自動化測試（Testing Pyramid） |
| 核心技術 | FastAPI / 原生 `sqlite3` / HTML5 + Tailwind CDN + 原生 JS |
| 測試技術 | pytest / httpx (TestClient) / Playwright (pytest-playwright) |
| 專案規模 | 3 個後端模組、2 個靜態頁面、43 個測試函式（97 個案例）、1 張資料表 |

---

## 二、學習目標

- 理解 **測試金字塔**：Unit / Web API / E2E 三層各自的測試邊界、依賴與成本
- 練習 **把業務邏輯抽成純函式**，讓驗證規則可以獨立、快速、完整地被測試
- 熟悉 **pytest fixture 與環境隔離**：`tmp_path` 沙盒資料庫、環境變數覆寫，確保測試零副作用
- 掌握 **multipart/form-data 上傳**、檔案落地與安全檔名（UUID4）策略
- 體會 **「文件本身也需要被測試」**：說明頁若與實作脫節，就會變成誤導

---

## 三、檔案結構

```text
HW06-/
├── README.md                    # 本檔案
└── resume-survey-app/
    ├── app/
    │   ├── __init__.py
    │   ├── main.py              # FastAPI 進入點、路由與靜態檔案掛載
    │   ├── database.py          # SQLite 連線與初始化表結構
    │   └── validators.py        # 獨立的商業邏輯驗證函式 (供 Unit Test 測試)
    ├── static/
    │   ├── index.html           # 履歷問卷填寫與已提交列表頁
    │   └── test-docs.html       # 測試架構、邏輯與案例介紹專頁
    ├── uploads/                 # 存放上傳的圖片 (需自動建立，加入 .gitkeep)
    ├── data/                    # 存放 SQLite 資料庫檔案 (resume.db)
    ├── tests/
    │   ├── conftest.py          # Pytest fixtures (包含測試用 DB 與環境隔離)
    │   ├── test_unit.py         # 單元測試
    │   ├── test_api.py          # 系統/API 測試
    │   └── test_e2e.py          # Playwright E2E 測試
    ├── requirements.txt
    └── README.md
```

### 3.1 資料表 Schema

單一資料表 `submissions`：

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

### 3.2 驗證邏輯（`app/validators.py`）

刻意**不 import FastAPI**，只使用標準函式庫，因此可以乾淨地做單元測試：

| 函式 | 規則 |
|---|---|
| `validate_email(email)` | 必須剛好一個 `@`、前後無空白、網域含至少 2 碼 TLD |
| `validate_experience(years)` | 嚴格型別 `int`（排除 `bool`），且 `0 <= years <= 50` |
| `validate_image_extension(filename)` | 以**最後一個**副檔名比對白名單 `.jpg/.jpeg/.png/.webp`（不分大小寫） |
| `generate_safe_filename(filename)` | 以 UUID4 取代原始檔名主體，保留（小寫）原副檔名 |

> `photo.jpg.exe` 這種雙副檔名繞過手法會被擋下，因為判定以最後一段副檔名為準。

### 3.3 API 規格

| 方法 | 路徑 | 說明 | 回應 |
|---|---|---|---|
| `GET` | `/` | 履歷問卷填寫頁 | `static/index.html` |
| `GET` | `/test-docs` | 測試說明專頁（內含互動式測試控制台） | `static/test-docs.html` |
| `POST` | `/api/submissions` | 送出履歷問卷（multipart/form-data） | `201` + 該筆資料 JSON |
| `GET` | `/api/submissions` | 取得所有履歷問卷（最新在前） | `200` + JSON 陣列 |
| `POST` | `/api/run-tests` | **開發者工具**：在網頁上直接執行測試 | `200` + 執行結果 JSON |

驗證失敗回傳 `400 Bad Request`；必要欄位未提供回傳 `422`。
兩種失敗語意刻意區分：**未提供**（框架處理）vs. **提供了但內容無效**（業務層處理）。

`POST /api/run-tests` 接受 `{"suite": "unit" | "api" | "e2e" | "e2e_headed" | "all"}`，
後端以 `subprocess.run([sys.executable, "-m", "pytest", "-v", "--tb=short", ...])` 執行，
回傳 `stdout` / `stderr` / `returncode` / `duration_seconds`。其中 `e2e_headed` 會加上
`--headed --slowmo 500`，讓使用者的桌面真的彈出 Chromium 視窗觀看自動填表。

---

## 四、使用方式

### 安裝

```bash
cd resume-survey-app
python -m pip install -r requirements.txt
python -m playwright install chromium      # 跑 E2E 測試時才需要
```

### 啟動

```bash
python -m uvicorn app.main:app --reload
```

| 網址 | 說明 |
|---|---|
| <http://127.0.0.1:8000/> | 履歷問卷填寫頁 |
| <http://127.0.0.1:8000/test-docs> | **測試架構與案例說明專頁** |
| <http://127.0.0.1:8000/docs> | Swagger UI |

---

## 五、測試

### 5.1 三層測試金字塔

| 層級 | 測試檔 | 測試邊界 | 依賴 DB | 依賴網路 | 執行成本 |
|---|---|---|---|---|---|
| **Unit** | `tests/test_unit.py` | `validators.py` 的純函式 | ✗ | ✗ | 數毫秒 |
| **Web API** | `tests/test_api.py` | HTTP 請求 → 驗證 → 落地 → 寫入 → JSON 回應 | ✓（沙盒） | ✗（in-process） | 毫秒級 |
| **E2E** | `tests/test_e2e.py` | 瀏覽器完整使用者旅程 | ✓（沙盒） | ✓（僅 localhost） | 秒級 |

完整的三層邊界說明、**43 個測試函式的案例對照表**（測試輸入 / 預期輸出 / 背後驗證邏輯）
與執行指令，都寫在 `/test-docs` 專頁裡。

### 5.2 互動式測試控制台

`/test-docs` 頁面把測試說明升級成可以「直接用」的開發工具：

| 功能 | 說明 |
|---|---|
| **Terminal 快速指令中心** | 6 張指令卡片（執行全部 / 僅單元 / 僅 API / 有頭慢動作 E2E / Trace Viewer / 只重跑失敗），每張右上角有「複製指令」按鈕，點擊後以 `navigator.clipboard.writeText()` 寫入剪貼簿，按鈕變成「✓ 已複製！」並在 1.8 秒後復原 |
| **網頁即時測試執行器** | 5 個按鈕直接在本頁呼叫 `POST /api/run-tests`，執行中顯示 loading 動畫，完成後以模擬終端機印出完整 pytest 輸出，並附綠燈／紅燈狀態徽章與總耗時 |

「👁️ 觀看 E2E 自動填表」會讓桌面真的彈出 Chromium 視窗，以 500ms 慢動作展示瀏覽器
自動填表、上傳圖片、送出並更新卡片列表。

### 5.3 執行指令

```bash
# 三層一次跑完
python -m pytest -v

# 分層執行
python -m pytest tests/test_unit.py -v     # Layer 1：純函式
python -m pytest tests/test_api.py  -v     # Layer 2：HTTP 契約
python -m pytest tests/test_e2e.py  -v     # Layer 3：瀏覽器旅程

# 有頭慢動作（桌面會彈出 Chromium 視窗）
python -m pytest tests/test_e2e.py --headed --slowmo 500 -v

# 開啟 Playwright Trace Viewer
python -m pytest tests/test_e2e.py --tracing=retain-on-failure -v
python -m playwright show-trace test-results/

# 只跑單元 + API（CI 快速守門）
python -m pytest tests/test_unit.py tests/test_api.py -v
```

### 5.4 測試隔離（零副作用）

測試**絕對不會**寫入正式的 `data/resume.db` 與 `uploads/`：

| 機制 | 說明 |
|---|---|
| `tmp_path` fixture | 每個 API 測試案例都拿到 `tmp_path/data/resume.db` 與 `tmp_path/uploads` |
| `tmp_path_factory` + uvicorn 子行程 | E2E 伺服器在獨立沙盒啟動，以 `RESUME_DB_PATH` / `RESUME_UPLOAD_DIR` 指向沙盒 |
| 匯入順序 | `conftest.py` **先**設定環境變數、**後** `import app.main`，避免模組層級的 `app = create_app()` 碰到正式路徑 |
| Mock 圖片 | 用 `io.BytesIO` + `zlib` 即時產生合法 PNG，repo 內不放二進位素材 |
| 網頁執行器再包一層 | `POST /api/run-tests` 啟動的子行程，其 `RESUME_DB_PATH` / `RESUME_UPLOAD_DIR` 會被覆寫成 `tempfile.TemporaryDirectory()`，執行完即刪除 |

### 5.5 防呆：避免「測試再觸發測試」

網頁上的「⚡ 執行全套測試」若沒有防呆，子行程會再跑一次全部測試，而那份測試又會呼叫
`/api/run-tests`… 形成無限遞迴。因此：

* 子行程一律帶上 `RESUME_RUN_TESTS_ACTIVE=1` 環境標記。
* 端點偵測到此標記時直接回傳 `409 Conflict`，前端顯示紅燈徽章而不是假裝成功。
* 受影響的 2 個 API 案例會自動 `pytest.skip()`，在最外層執行時則正常運作。

### 5.6 執行結果

```
tests/test_unit.py .......  67 passed     (13 個測試函式)
tests/test_api.py  .......  21 passed     (21 個測試函式)
tests/test_e2e.py  .......   9 passed     ( 9 個測試函式)
====================================================
97 passed
```

---

## 六、設計取舍（奧卡姆剃刀）

| 決策 | 理由 |
|---|---|
| 原生 `sqlite3` 而非 ORM | 單表、單一 CRUD，ORM 只會增加層數與遷移負擔 |
| `create_app(db_path, upload_dir)` 工廠函式 | 讓測試能直接指定沙盒路徑，不必靠 monkeypatch 全域狀態 |
| 驗證邏輯抽成純函式 | 業務規則只有一份，Unit / API / E2E 三層共用同一套判斷 |
| 前端不打包 | 原生 HTML + Tailwind CDN + Fetch API，沒有建置步驟就不會有建置壞掉的一天 |
| 檔名用 UUID4 | 同名檔案不互相覆蓋，原始檔名帶來的路徑穿越也自動失效 |
| 頁面風格 | 視覺說明頁用 CSS 變數手寫，維持零依賴 |
| `/api/run-tests` 用 `def` 而非 `async def` | FastAPI 會把同步端點丟到 threadpool，測試跑 30 秒網頁也不會被卡住 |
| 指令一律 `python -m pytest` | 避免多版本 Python 的套件版本衝突，貼到任何環境都跑得動 |

---

## 七、延伸 / 參考

- **可改進**：分頁查詢、Email 唯一性驗證、圖片壓縮、支援多職位類別
- **參考資源**
  - [FastAPI 官方教學](https://fastapi.tiangolo.com/tutorial/)
  - [Testing FastAPI](https://fastapi.tiangolo.com/tutorial/testing/)
  - [pytest 官方文件](https://docs.pytest.org/)
  - [Playwright Python](https://playwright.dev/python/)
  - [Martin Fowler — Test Pyramid](https://martinfowler.com/articles/microservices.html)

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
