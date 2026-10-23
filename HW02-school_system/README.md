# NKU 校務資訊系統 — 現代化重構

> 現代軟體工程 · HW2 · 以 **Python Flask + 原生 Vanilla JS** 重建「金門大學校務資訊系統」原型，支援 3000+ 使用者規模、資料驅動的左側選單、與完整的人員/公告管理後台。

## 學習目標

1. 從無到有規劃並實作一個具備權限模型、CRUD、批次匯入 與 AJAX 局部載入的後台系統。
2. 練習「資料層 / 服務層 / 路由層 / 前端組件」的分層架構。
3. 體驗**語意化版本**迭代（v0.1 → v1.0）的開發節奏。
4. 為前後端分別建立**自動化測試**：後端用 `pytest`、前端用 Node 內建 `node:test`。

## 版本路線圖

| 版本 | 範圍 | 狀態 |
|------|------|------|
| v0.1.0 | 骨架：Flask + SQLite + `/api/menu` + 基本模板 | ✅ |
| v0.2.0 | 現代化 sidebar：CSS 變數、遞迴渲染、即時搜尋、狀態持久化 | ✅ |
| v0.3.0 | Header + 修改密碼 modal + 隱藏選單動畫 + AJAX 路由切換 | ✅ |
| v0.4.0 | Admin CMS：選單 CRUD + 公告編輯器 | ✅ |
| v1.0.0 | 人員管理 2.0：系所/學年/Email + CSV 批次匯入 + 完整測試 | ✅ |

## 技術棧

- **後端**：Python 3.10+、Flask 3.0、Werkzeug（scrypt / pbkdf2 hash）、SQLite
- **前端**：原生 Vanilla JS（ES 模組、無框架）、CSS Variables
- **測試**：pytest 8 + node:test（內建）
- **資料**：CSV（UTF-8 BOM，Excel / LibreOffice 都能直接打開）

無 npm、無 Docker、無資料庫伺服器。

---

## 快速啟動

### Windows（推薦）

直接雙擊 `start.bat`，會自動安裝依賴（首次）並啟動 server：

```
瀏覽器：http://127.0.0.1:5000
停止伺服器：雙擊 stop.bat
```

### 命令列

```bash
python -m pip install -r requirements.txt
set FLASK_DEBUG=0          # Windows; macOS/Linux: export FLASK_DEBUG=0
python app.py
```

`FLASK_DEBUG=0` 會關閉 Werkzeug auto-reload，避免 watchdog 反覆重啟影響首次載入。

---

## 預設帳號（seed）

| username / Email | password | 角色 | 學號 | 系所 |
|------------------|----------|------|------|------|
| `feng` 或 `feng@nku.edu.tw` | `pass1234` | student | 111210501 | 資訊工程學系 |
| `wang` | `pass1234` | student | 111210502 | 資訊工程學系 |
| `lin` | `pass1234` | student | 110210001 | 資訊工程學系 |
| `chen` | `pass1234` | student | 112210101 | 企業管理學系 |
| `teacher01` | `pass1234` | teacher | — | 資訊工程學系 |
| `admin` 或 `admin@nku.edu.tw` | `admin1234` | admin | — | 資訊處 |

> 登入接受 **username / 學號 / email** 任一。
> Demo 小技巧：以 `admin` 登入後，首頁的「角色切換」下拉可在不改變真實帳號的情況下，暫時切換成 student / teacher 觀察選單變化。

### 預設系所（16 個）

CS / EE / ME / CE / BA / AC / FN / EC / LA / FL / CH / ES / PE / ADM / OAS / OSA

---

## 執行測試

### 後端 + 前端單元（pytest + node:test）

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts\test.ps1

# macOS / Linux
bash scripts/test.sh
```

### 瀏覽器 E2E（Playwright + node:test）

E2E 測試位於 `tests/e2e/`，會自動 spawn 一個 Flask 子進程（tmp DB、port 5001），跑完自動關閉。**不需要手動啟動 server。**

```bash
# 第一次需要安裝瀏覽器（已完成可跳過）
npx playwright install chromium

# 跑全部 e2e
npm run test:e2e

# 只想看某個旅程
npm run test:e2e:01-login
npm run test:e2e:02-sidebar
npm run test:e2e:03-announcements
npm run test:e2e:04-users
npm run test:e2e:05-password

# Headed 模式（看瀏覽器自動操作）
npm run test:e2e:headed

# 只做語法檢查（不啟動 server、不開瀏覽器）
npm run test:e2e:check
```

> ⚠️ e2e 預設 headless。如果要看老師上課那種瀏覽器自動操作的畫面，用 `npm run test:e2e:headed`。

當前覆蓋：

- **後端**：`pytest` 106 個測試
  - API（含 auth、menu、announcement、admin、users、departments）
  - services（含 CRUD、搜尋、CSV、密碼 hash、權限）
  - Markdown 渲染、CSV 匯入/匯出 round-trip
  - 端對端流程、form fallback 登入
  - **3000+ 使用者 scale / 索引 EXPLAIN 驗證 / 效能斷言**
  - JS import path 解析 + `node --check` 語法檢查
- **前端單元**：`node:test` 17 個測試（純函數 tree + highlight）
- **瀏覽器 E2E**：`tests/e2e/`（Playwright + `node:test`）
  - `01-login-home.spec.mjs` — 登入、表單 fallback、角色可見性、登出
  - `02-sidebar-router.spec.mjs` — 選單樹、即時搜尋高亮、AJAX 切換、瀏覽器上一頁、隱藏選單
  - `03-announcements.spec.mjs` — 學生瀏覽 + 管理員 CRUD
  - `04-users-admin.spec.mjs` — 列表 / 篩選 / 抽屜編輯 / 重設密碼 / 刪除 / 模板下載 / CSV 匯入 / 權限
  - `05-change-password-logout.spec.mjs` — 修改密碼 modal、登出

---

## 檔案結構

```
HW02-/
├── app.py                          # Flask entrypoint
├── config.py                       # Config / TestConfig
├── start.bat / stop.bat            # Windows 啟動 / 停止
├── requirements.txt
├── models/
│   ├── __init__.py
│   └── db.py                       # SQLite + schema + seed loader + migration
├── services/
│   ├── __init__.py
│   ├── menu_service.py             # tree / filter / CRUD
│   ├── announcement_service.py     # list / get / upsert / delete
│   ├── auth_service.py             # login (username OR email) / role-switch / change-password
│   ├── user_service.py             # CRUD + 搜尋/分頁 + CSV bulk import/export + 級別計算
│   ├── department_service.py       # CRUD
│   └── markdown.py                 # tiny Markdown -> HTML
├── routes/
│   ├── __init__.py
│   ├── page_routes.py              # /, /login, POST /login, GET /logout
│   ├── page_partial_routes.py      # /page/<subpath>  HTML partials（AJAX / 直接訪問兩種模式）
│   ├── menu_routes.py              # /api/menu（flat list）
│   ├── auth_routes.py              # /api/auth/*
│   ├── announcement_routes.py      # /api/announcements
│   └── admin_routes.py             # /api/admin/*（menu, announcement, user, department, CSV）
├── templates/
│   ├── base.html
│   ├── index.html                  # 主版（已登入）
│   ├── index_with_partial.html     # 直接訪問 /page/... 時用
│   ├── login.html
│   ├── _macros.html                # server-side sidebar renderer
│   └── pages/
│       ├── home.html
│       ├── announcement_detail.html
│       ├── announcement_list.html
│       ├── courses.html
│       ├── grades.html
│       ├── admin_menu.html
│       ├── admin_announcements.html
│       ├── admin_users.html        # 含 CSV 匯入結果 modal + 抽屜編輯
│       └── placeholder.html
├── static/
│   ├── css/  (reset, variables, layout, header, sidebar, main, modal, announcement, admin)
│   ├── js/
│   │   ├── app.js                  # entry
│   │   ├── config.js
│   │   ├── core/   (api, dom, storage)
│   │   ├── utils/  (tree, highlight)         # 純函數 (可單元測試)
│   │   ├── components/  (sidebar, header, modal, router)
│   │   └── pages/  (login, announcement-list, admin_menu, admin_announcements, admin_users)
│   └── img/logo.svg
├── data/
│   ├── seed_menu.json              # 44 個選單節點（6 大類 + admin）
│   ├── seed_users.json             # 7 個預設帳號（學號 + email）
│   ├── seed_departments.json       # 16 個系所
│   └── seed_announcements.json
├── tests/
│   ├── conftest.py
│   ├── test_services.py / test_announcements.py / test_admin.py
│   ├── test_admin_users.py / test_partials.py / test_pages.py
│   ├── test_e2e.py / test_form_login.py
│   ├── test_markdown.py / test_csv_import.py / test_user_scale.py
│   ├── test_js_imports.py
│   ├── js/  (test_tree.mjs, test_highlight.mjs)
│   └── e2e/                          # 瀏覽器 e2e (Playwright + node:test)
│       ├── helpers/  (server.mjs, fixtures.mjs, selectors.mjs)
│       └── *.spec.mjs  (01-login / 02-sidebar / 03-announcements / 04-users / 05-password)
└── scripts/  (test.sh, test.ps1)
```

---

## REST API 一覽

### Auth

| Method | Path | 說明 | 權限 |
|--------|------|------|------|
| POST | `/api/auth/login` | 接受 username / email + 密碼 | 公開 |
| POST | `/api/auth/logout` | 登出 | 已登入 |
| GET | `/api/auth/me` | 取得當前使用者（含 current_grade） | 已登入 |
| POST | `/api/auth/switch-role` | Demo 暫時切換角色 | 已登入 |
| POST | `/api/auth/change-password` | 舊密碼驗證 + 雜湊更新 | 已登入 |

### Menu

| Method | Path | 說明 | 權限 |
|--------|------|------|------|
| GET | `/api/menu` | 依角色回傳 flat list（client build tree） | 已登入 |

### Announcements

| Method | Path | 說明 | 權限 |
|--------|------|------|------|
| GET | `/api/announcements` | 公告列表 | 已登入 |
| GET | `/api/announcements/<slug>` | 單則公告 | 已登入 |

### Admin — Menus & Announcements

| Method | Path | 說明 |
|--------|------|------|
| GET / POST / PUT / DELETE | `/api/admin/menu[/{id}]` | 完整 CRUD |
| GET / POST / DELETE | `/api/admin/announcements[/<slug>]` | CMS |

### Admin — Users

| Method | Path | 說明 |
|--------|------|------|
| GET | `/api/admin/users?q=&role=&status=&department_id=&year_enrolled=&page=&per_page=` | 列表 + 篩選 + 分頁 |
| GET | `/api/admin/users/<id>` | 單筆 |
| POST | `/api/admin/users` | 新增 |
| PUT | `/api/admin/users/<id>` | 修改（不可降級/停用最後一個啟用中的 admin） |
| DELETE | `/api/admin/users/<id>` | 刪除（不可刪自己） |
| POST | `/api/admin/users/<id>/reset-password` | admin 重設密碼 |
| **GET** | **`/api/admin/users/template.csv`** | **下載匯入模板** |
| **GET** | **`/api/admin/users/export.csv`** | **匯出現有人員（不包含密碼）** |
| **POST** | **`/api/admin/users/import`** | **批次匯入（multipart / text / JSON）** |

### Admin — Departments

| Method | Path | 說明 |
|--------|------|------|
| GET / POST / PUT / DELETE | `/api/admin/departments[/{id}]` | 拒絕刪除有人員的系所 |

### Page Partials (AJAX)

| Method | Path | 說明 |
|--------|------|------|
| GET | `/page/<subpath>` | AJAX 回 partial；直接訪問回完整頁 |

---

## 設計重點

### 1. 資料模型

**Schema**（`models/db.py`）
- `users`：username / email / password_hash / display_name / department_id / role / status / student_id / year_enrolled / class_name / phone / note
- `departments`：code / name / short_name / sort_order
- `menu_items`：parent_id 自參考、`required_role` 決定可見性
- `announcements`：slug / title / content / author

**Migration**：
- `_apply_user_migrations()` 對舊 DB 做 `ALTER TABLE ADD COLUMN`，index 建立前會先檢查 column 是否存在（避免舊 DB 沒有新欄位時 CREATE INDEX 失敗）
- 不存 `current_grade`：用 `compute_grade(year_enrolled, current_year)` 即時計算

**效能（3000+ scale 驗證過）**：
- 5 個索引：username (UNIQUE)、email (UNIQUE partial)、role、status、department_id、year_enrolled
- 50 筆分頁 < 3ms、3000 筆 filter < 2ms

### 2. 左側選單

- **資料驅動遞迴渲染**：`static/js/components/sidebar.js` 中 `Sidebar.renderNodes()` 純遞迴，無寫死 HTML
- **server-side fallback**：`templates/_macros.html` 在 server 端先用 Jinja 渲染，client-side JS 接管互動
- **即時快搜**：`utils/tree.js:filterTree` 純函數過濾；`utils/highlight.js` 將關鍵字以 `<mark>` 高亮；符合條件的父節點會自動展開
- **狀態記憶**：`localStorage` 儲存展開集合、active 路由、隱藏狀態

### 3. Header / Modal / Router

- 三欄 grid：校徽+標題（左）、按鈕（中）、學期+用戶+登出（右）
- 修改密碼：原生 `<dialog>` + `werkzeug.security` 雜湊
- 隱藏選單：`grid-template-columns` 平滑收合
- **AJAX router**：攔截 `a[data-route]`，fetch `/page/<subpath>` partial 並注入
- **page_partial_routes 兩種模式**：
  - `X-Requested-With: fetch` → 回 partial
  - 直接瀏覽器訪問 → 回 `index_with_partial.html`（含完整 layout）
- `popstate` 支援瀏覽器上一頁/下一頁

### 4. 人員管理（Admin）

- 表格 + 篩選（搜尋 / 角色 / 狀態 / 系所）+ 分頁
- 抽屜式編輯（slide-in panel）：4 個 fieldset（基本資料 / 角色狀態 / 學籍 / 聯絡）
- 「學籍」section 依角色切換顯示
- 重設密碼 modal
- 列表顯示「年級」（即時計算）+ Email + 班級 + 系所代碼

### 5. CSV 批次匯入

**模板格式**（`GET /api/admin/users/template.csv`）：

```csv
username,password,display_name,department_code,role,student_id,email,phone,year_enrolled,class_name,status,note
111210503,pass1234,王小明,CS,student,111210503,wang3@nku.edu.tw,0912-000-003,111,資工二A,active,示範
T010,pass1234,陳老師,EE,teacher,,t010@nku.edu.tw,082-313-010,,,active,
```

**支援**：
- 中文別名（帳號 / 密碼 / 姓名 / 信箱 / 電話 / 學號 / 學年 / 系所 / 狀態 / 備註）
- UTF-8 BOM（Excel 直接開）
- 三種上傳格式：multipart / `text/csv` body / JSON `{csv: "..."}`
- 跳過重複帳號（預設）/ 嚴格模式
- 列級錯誤報告（哪一行、什麼錯）
- 空欄 `password` 時使用 `default_password` 參數

**匯出**（`GET /api/admin/users/export.csv`）：
- UTF-8 BOM、可附加 role/status/department_id filter
- **不包含密碼**（避免外洩）

### 6. 防呆

- 不能停用/降級/刪除最後一個啟用中的 admin
- API 401 自動跳轉到 `/login` 並 bounce
- 表單 POST fallback：JS 壞了也能登入
- 學生帳號被停用就無法 authenticate

---

## 已知限制 / 未來延伸

- 密碼強度規則僅要求 ≥4 字元；真實部署應加上大小寫 + 數字 + 符號
- 公告 Markdown 渲染器為自製最小集，不支援表格 / 圖片
- 沒有真實 LDAP / SSO 整合，僅 mock 三帳號
- 沒有 i18n；目前全中文
- 大檔匯入目前全 in-memory 解析；>10MB CSV 建議改 streaming

---

## 參考

- [Flask 3.0 docs](https://flask.palletsprojects.com/)
- [werkzeug.security](https://werkzeug.palletsprojects.com/en/stable/utils/#module-werkzeug.security)
- [Node.js test runner](https://nodejs.org/api/test.html)
- [Python csv 模組](https://docs.python.org/3/library/csv.html)
- [CSS Variables](https://developer.mozilla.org/en-US/docs/Web/CSS/--*)
