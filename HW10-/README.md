# HW10 — (主題待定)

> 現代軟體工程 · HW10 · (一句話描述這個作業在學什麼)

🔙 [回首頁](../)

## 待辦

- [ ] 主題 / 學習目標
- [ ] 檔案結構
- [ ] 使用方式
- [ ] 測試
- [ ] 延伸 / 參考

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
