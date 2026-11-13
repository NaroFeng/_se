/**
 * lib/init.js
 * ---------------------------------------------------------------
 * `html-block init`：一鍵建立標準範例結構，讓初學者開箱即用。
 *
 * 只建立「不存在」的檔案，已存在的檔案一律保留（不覆蓋使用者的作品）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { createLogger } from './logger.js';

/** 範例檔案內容 */
export const SAMPLES = {
  'src/pages/index.html': `<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{title | 我的第一個網站}}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <!-- ① 引用區塊：src 直接寫檔名，工具會到 src/blocks/ 底下找 -->
  <block src="navbar.html" brand="MySite" title="首頁"></block>

  <main class="container">
    <h1>{{title | 歡迎來到我的網站}}</h1>
    <p class="lead">
      這個頁面是由 <code>src/pages/index.html</code> 組裝出來的。
      請不要直接修改根目錄的 <code>index.html</code>，它每次 build 都會被覆寫。
    </p>

    <div class="cards">
      <!-- ② 傳入屬性（title / desc）+ 插槽內容 -->
      <block src="card.html" title="免費模板" desc="開箱即用的 HTML 版面">
        <p class="card-custom">👋 這段文字是透過 &lt;slot&gt; 插槽傳入的，會取代 card.html 裡的預設內容。</p>
      </block>

      <!-- ③ src 可以省略 .html 副檔名 -->
      <block src="card" title="單層平鋪" desc="src 寫 card 一樣找得到 card.html"></block>

      <!-- ④ 沒傳 desc 會用預設值；沒傳插槽內容則保留預設內容 -->
      <block src="card.html" title="預設值示範"></block>
    </div>
  </main>

  <!-- ⑤ 區塊也可以互相巢狀引用 -->
  <block src="footer.html" year="2026" brand="MySite"></block>
</body>
</html>
`,

  'src/blocks/navbar.html': `<nav class="navbar">
  <a class="navbar-brand" href="index.html">{{brand | MySite}}</a>
  <ul class="navbar-links">
    <li><a href="index.html">首頁</a></li>
    <li><a href="about.html">關於我們</a></li>
    <li><a href="contact.html">聯絡我們</a></li>
  </ul>
  <p class="navbar-hint">目前頁面：{{title | 首頁}}</p>
</nav>
`,

  'src/blocks/footer.html': `<footer class="footer">
  <p class="footer-copy">© {{year | 2026}} {{brand | MySite}} ・ 本頁由 html-block 自動組裝</p>
</footer>
`,

  'src/blocks/card.html': `<article class="card">
  <h2 class="card-title">{{title | 未命名區塊}}</h2>
  <p class="card-desc">{{desc | 這張卡片還沒有描述。}}</p>
  <div class="card-body">
    <slot>這是預設內容。只要在 &lt;block&gt; 標籤內放入子元素，就會取代這段文字。</slot>
  </div>
  <a class="card-link" href="#">了解更多 →</a>
</article>
`,

  'css/style.css': `/* 靜態資源直接放在專案根目錄，工具完全不會搬移它們。 */
:root {
  --brand: #2563eb;
  --text: #1f2937;
  --muted: #6b7280;
  --border: #e5e7eb;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: system-ui, -apple-system, "Noto Sans TC", sans-serif;
  color: var(--text);
  line-height: 1.7;
}

.navbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
}

.navbar-brand { font-weight: 700; font-size: 20px; color: var(--brand); text-decoration: none; }
.navbar-links { display: flex; gap: 16px; list-style: none; margin: 0; padding: 0; }
.navbar-links a { color: var(--text); text-decoration: none; }
.navbar-links a:hover { color: var(--brand); }
.navbar-hint { margin-left: auto; margin-bottom: 0; color: var(--muted); font-size: 14px; }

.container { max-width: 960px; margin: 0 auto; padding: 40px 24px; }
.lead { color: var(--muted); }

.cards { display: grid; gap: 20px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }

.card {
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, .04);
}
.card-title { margin: 0 0 8px; font-size: 18px; }
.card-desc { margin: 0 0 12px; color: var(--muted); font-size: 15px; }
.card-body { font-size: 15px; }
.card-custom { margin: 0; padding: 10px; background: #eff6ff; border-radius: 8px; }
.card-link { color: var(--brand); font-size: 14px; text-decoration: none; }

.footer {
  border-top: 1px solid var(--border);
  padding: 20px 24px;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
}
.footer-copy { margin: 0; }
`,
};

/**
 * 在指定目錄建立範例結構。
 * @returns {{ created: string[], skipped: string[] }}
 */
export function initProject(options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const logger = options.logger ?? createLogger();

  const created = [];
  const skipped = [];

  for (const [relativePath, content] of Object.entries(SAMPLES)) {
    const target = path.join(cwd, relativePath);
    if (fs.existsSync(target)) {
      skipped.push(relativePath);
      continue;
    }
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content, 'utf8');
    created.push(relativePath);
  }

  if (created.length > 0) {
    for (const relativePath of created) {
      logger.success(`已建立 ${relativePath}`);
    }
  }
  if (skipped.length > 0) {
    for (const relativePath of skipped) {
      logger.info(`已存在，略過：${relativePath}`);
    }
  }

  return { created, skipped };
}

export default initProject;
