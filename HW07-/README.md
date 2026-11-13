# html-block-assembler

> 建置期 HTML 區塊組裝 CLI 套件 — 專為 HTML 初學者設計

把重複的 HTML（導覽列、頁尾、卡片…）拆成獨立的「區塊檔」，在**建置期**自動組裝成完整網頁。
不需要安裝任何框架、不需要理解複雜的相對路徑、不需要處理子目錄。

---

## 設計哲學

| 原則 | 說明 |
| --- | --- |
| **單層平鋪架構** | `src/pages/` 與 `src/blocks/` 底下只放 `.html` 檔案，不使用子資料夾。 |
| **直接輸出至專案根目錄** | 編譯結果直接放在專案根目錄，靜態資源（`css/`、`js/`、`images/`）的路徑完全不用改。 |
| **不刪除任何檔案** | 永遠只做「同名 `.html` 單點覆寫」，絕不清空輸出目錄。 |
| **不讓初學者崩潰** | 找不到區塊、寫錯路徑、循環引用 → 印出清楚的中文錯誤，並在頁面上留下醒目的錯誤提示框。 |

---

## 快速開始

```bash
npm install

# ① 一鍵建立範例結構
node ./bin/cli.js init

# ② 組裝成根目錄的 index.html
node ./bin/cli.js build

# ③ 邊改邊看（自動重新組裝）
node ./bin/cli.js watch
```

安裝成全域指令後，也可以直接用 `npx html-block <指令>`。

### 從 npm 安裝

本套件已發佈到 npm：

```bash
# 一次性的（不需安裝，直接跑）
npx html-block-assembler init
npx html-block-assembler build
npx html-block-assembler watch

# 或安裝成全域指令
npm install -g html-block-assembler
html-block init
```

> 套件名稱 `html-block-assembler`，指令名稱 `html-block`。
> 環境需求：Node.js **v18.3.0 以上**。

---

## 目錄結構

```
專案根目錄/
├── src/
│   ├── pages/          ← 你的頁面（只放 .html，單層）
│   │   └── index.html
│   └── blocks/         ← 可重複使用的區塊（只放 .html，單層）
│       ├── navbar.html
│       ├── footer.html
│       └── card.html
├── css/ js/ images/    ← 靜態資源（工具完全不碰它們）
└── index.html          ← 組裝結果（自動產生，請勿手動修改）
```

> 為什麼輸出在根目錄？因為 `src/pages/index.html` 裡寫 `src="images/pic.jpg"`，
> 組裝到根目錄之後就會變成 `index.html` 去找 `images/pic.jpg` — 路徑完全不用改。

---

## 指令

### `npx html-block init`

在當前目錄建立標準範例結構（**已存在的檔案不會被覆寫**）：

- `src/pages/index.html`
- `src/blocks/navbar.html`
- `src/blocks/footer.html`
- `src/blocks/card.html`
- `css/style.css`

### `npx html-block build [--src <dir>] [--out <dir>] [--no-comments]`

| 選項 | 預設值 | 說明 |
| --- | --- | --- |
| `--src <dir>` | `./src` | 來源目錄 |
| `--out <dir>` | `./` | 輸出目錄（專案根目錄） |
| `--no-comments` | 關閉 | 不產生 `[BLOCK START/END]` 區塊邊界註解 |

把 `src/pages/*.html` 組裝成完整網頁，輸出到 `--out` 目錄（同名覆寫）。

### `npx html-block watch [--src <dir>] [--out <dir>]`

啟動一次完整 build，接著監聽 `src/` 的檔案變更並自動重新組裝，會印出每次的狀態與耗時（ms）。

> ⚠️ 只監聽 `src/` 底下的 `.html`，**絕不監聽根目錄的 `.html`**，
> 否則編譯產出的 `index.html` 會再次觸發 watch → 無限迴圈！

---

## 語法

### ⚠️ 嚴格語法規範：`<block>` 必須成對閉合

`<block>` **只允許成對閉合**的寫法：

```html
✅ <block src="navbar.html"></block>     <!-- 正確 -->
❌ <block src="navbar.html" />           <!-- 錯誤：不支援自閉合 -->
❌ <block src="navbar.html">             <!-- 錯誤：缺少結束標籤 -->
```

**為什麼要嚴格？**

`<block />` 這種自閉合寫法在 HTML5 的自訂標籤語意下，瀏覽器會把它當成「開啟標籤」，
導致後面的整頁內容都被包進 `<block>` 裡，結果就是**後面的內容被誤當成 slot 吞掉**。
為了避免這種難以除錯的狀況，本工具採取嚴格規範：寫法不合法就直接視為語法錯誤。

偵測到不合法寫法時會：

1. 在終端機印出紅色中文錯誤。
2. 在 HTML 原位置留下醒目的錯誤提示框（`<!-- [ERROR: ...] -->`）。
3. **只取代掉那個不合法標籤本身**，後面的頁面內容完整保留，不會被吞掉。

| 你寫的 | 結果 |
| --- | --- |
| `<block src="a.html" />` | `✖ <block> 不支援自閉合 /> 寫法，請使用完整的 <block src="..."></block>` |
| `<block src="a.html">` | `✖ <block> 缺少結束標籤 </block>，請使用完整的 <block src="..."></block>` |
| `</block>`（沒有對應的開標籤） | `✖ 有多餘的 </block> 結束標籤，沒有可以配對的 <block> 起始標籤` |

> HTML 註解裡的 `<block ... />` 不會被誤判。

---

### 1. 引用區塊

```html
<block src="navbar.html"></block>
```

`src` 一律相對於 `src/blocks/` 解析，初學者不需要煩惱相對路徑：

| 你寫的 | 實際會去找 |
| --- | --- |
| `navbar.html` | `src/blocks/navbar.html` |
| `navbar` | `src/blocks/navbar.html`（自動補上副檔名） |
| `../blocks/navbar.html` | `src/blocks/navbar.html`（取 basename，相容寫法） |

### 2. 屬性參數插值

```html
<!-- 頁面 -->
<block src="navbar.html" title="首頁"></block>

<!-- src/blocks/navbar.html -->
<nav><span>{{title}}</span></nav>
```

輸出：`<nav><span>首頁</span></nav>`

支援預設值語法 `{{key | 預設文字}}`：

```html
<nav><span>{{title | 首頁}}</span></nav>
```

| 情況 | 結果 |
| --- | --- |
| 有傳入 `title` | 使用傳入的值 |
| 沒傳入，但有寫預設值 | 使用預設值 |
| 沒傳入，也沒有預設值 | 清成空字串 `""`（不會殘留 `{{...}}`） |

### 3. Slot（內容插槽）

區塊檔裡放一個 `<slot>`，就能接收外部傳入的內容：

```html
<!-- src/blocks/card.html -->
<article>
  <h2>{{title | 未命名}}</h2>
  <slot>這是預設內容。</slot>
</article>
```

```html
<!-- 頁面：有傳內容 → 取代預設內容 -->
<block src="card.html" title="免費模板">
  <p>自訂內文</p>
</block>

<!-- 頁面：沒傳內容 → 保留預設內容 -->
<block src="card.html" title="免費模板"></block>
```

### 4. 巢狀引用與循環防護

區塊裡可以再引用其他區塊：

```html
<!-- src/blocks/layout.html -->
<div class="layout">
  <block src="navbar.html"></block>
  <block src="footer.html"></block>
</div>
```

如果不小心造成循環（`A → B → A`），工具會攔截下來並印出中文錯誤，不會卡死：

```
✖ 偵測到循環引用：a.html → b.html → a.html。已中止這個區塊的展開，避免無限迴圈。
```

---

## 產出結果

每個輸出檔案的**第一行**都會自動加上防呆警告：

```html
<!-- ⚠️ 警告：此檔案由 html-block 自動組裝生成，請勿直接修改！請至 src/pages/index.html 進行編輯 ⚠️ -->
```

每個展開的區塊前後會加上邊界註解（`--no-comments` 可關閉）：

```html
<!-- [BLOCK START: src/blocks/navbar.html] -->
<nav>…</nav>
<!-- [BLOCK END: src/blocks/navbar.html] -->
```

---

## 錯誤處理

| 情況 | 行為 |
| --- | --- |
| 找不到區塊檔 | 印紅色錯誤，頁面原位置留下 `<!-- [ERROR: 找不到區塊 xxx.html] -->` 與醒目錯誤提示框，**整個建置不會中斷** |
| `<block>` 缺少 `src` | 同上，提示缺少屬性 |
| `<block />` 自閉合 / 缺少 `</block>` | 視為語法錯誤，印紅色錯誤並留下錯誤提示框，**後面的內容不會被吞掉** |
| 多餘的 `</block>` | 視為語法錯誤，印紅色錯誤並留下錯誤提示框 |
| 循環引用 | 印出呼叫鏈並中止該區塊的展開 |
| `src/pages/` 或 `src/blocks/` 出現子目錄 | 印黃色警告「已忽略子目錄：xxx」並跳過（單層平鋪約束） |

---

## 專案結構

```
html-block-assembler/
├── bin/cli.js          # CLI 進入點（util.parseArgs）
├── lib/compiler.js     # 核心編譯引擎（node-html-parser）
├── lib/watcher.js      # Watch 模式（chokidar）
├── lib/init.js         # init 範例產生器
├── lib/logger.js       # 彩色終端機輸出
├── test/               # node --test 測試
├── LICENSE
└── package.json
```

### 技術選型

| 套件 | 用途 |
| --- | --- |
| `node-html-parser` | 解析與操作 HTML DOM/AST（`<block>` 標籤一律走 DOM，**不使用 Regex 解析標籤**） |
| `chokidar` | Watch 模式監聽 `src/` 檔案變更 |
| `picocolors` | 終端機彩色友善中文提示 |
| Node.js `util.parseArgs` | CLI 參數解析（無額外依賴） |

> **關於「嚴格語法檢查」與 DOM 的分工**：區塊的**展開** 100% 由 DOM/AST 驅動。
> 但 `<block ... />`（自閉合）與 `<block ...>`（未閉合）這兩種寫法，
> HTML 解析器要嘛把它當成空元素、要嘛直接從 DOM 裡丟棄，
> 從 DOM 端**看不出來**它們寫錯了 ——
> 因此語法檢查另外走一個「原始碼層級的字元掃描器」（非 Regex），
> 專門找出這些不合法寫法，展開邏輯本身完全不受影響。

### 環境需求

- Node.js **v18.3.0 以上**（需要 `util.parseArgs`）

---

## 測試

```bash
npm test
```

涵蓋：區塊展開、屬性插值、預設值、slot 插槽、找不到區塊、循環引用、巢狀引用、
單層平鋪約束、輸出目錄安全性（不刪檔）、BOM 處理、
**嚴格語法規範**（自閉合 `<block />`、未閉合 `<block>`、多餘 `</block>`、註解不誤判）、
多同層區塊的位移安全。

---

## 授權

MIT © 2026 NaroFeng — 詳見 [LICENSE](./LICENSE)
