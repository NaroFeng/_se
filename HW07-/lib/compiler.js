/**
 * lib/compiler.js
 * ---------------------------------------------------------------
 * html-block-assembler 核心編譯引擎
 *
 * 設計哲學：
 *  1. 「單層平鋪架構」：src/pages 與 src/blocks 只處理第一層的 .html 檔案，
 *     發現子目錄就跳過並溫柔提醒。
 *  2. 「直接輸出至專案根目錄」：輸出目錄預設是專案根目錄，
 *     所以絕對不能清空輸出目錄，只能做「同名 .html 單點覆寫」。
 *  3. 區塊標籤一律透過 node-html-parser 的 DOM/AST 尋找，
 *     嚴禁使用 Regex 去解析 <block> 標籤（Regex 僅用於 {{}} 佔位符插值）。
 */
import fs from 'node:fs';
import path from 'node:path';
import { parse } from 'node-html-parser';
import { createLogger } from './logger.js';

/** 區塊標籤名稱 */
export const BLOCK_TAG = 'block';
/** 插槽標籤名稱 */
export const SLOT_TAG = 'slot';

/**
 * 產生檔案最上方的防呆警告註解。
 * @param {string} pageLabel 來源頁面路徑，例如 src/pages/index.html
 */
export function warningComment(pageLabel) {
  return `<!-- ⚠️ 警告：此檔案由 html-block 自動組裝生成，請勿直接修改！請至 ${pageLabel} 進行編輯 ⚠️ -->`;
}

/* ------------------------------------------------------------------ *
 * 小工具
 * ------------------------------------------------------------------ */

/** 把絕對路徑轉成「相對 cwd、正斜線」的友善顯示路徑 */
function relLabel(target, cwd, fallback = null) {
  const rel = path.relative(cwd, target).split(path.sep).join('/');
  if (rel && !rel.startsWith('..')) return rel;
  return fallback ?? path.basename(target);
}

/** 判斷 target 是否位於 parent 之内（含自己） */
function isInside(target, parent) {
  const rel = path.relative(parent, target);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/** 把相對路徑轉成絕對路徑 */
export function resolveDir(dir, cwd = process.cwd()) {
  return path.resolve(cwd, dir ?? '.');
}

/**
 * 佔位符插值：
 *   {{key}}            → 取 attributes.key，沒有就清成空字串
 *   {{key | 預設文字}}  → 取 attributes.key，沒有就用預設文字
 */
const PLACEHOLDER_RE = /\{\{([^{}]*)\}\}/g;

export function interpolate(text, attributes = {}) {
  if (typeof text !== 'string' || text.indexOf('{{') === -1) return text;

  return text.replace(PLACEHOLDER_RE, (_match, body) => {
    const raw = String(body);
    const pipeIndex = raw.indexOf('|');
    const key = (pipeIndex === -1 ? raw : raw.slice(0, pipeIndex)).trim();
    const fallback = pipeIndex === -1 ? undefined : raw.slice(pipeIndex + 1).trim();

    if (key && Object.prototype.hasOwnProperty.call(attributes, key)) {
      const value = attributes[key];
      return value === undefined || value === null ? '' : String(value);
    }
    // 沒有對應屬性：有預設值就用預設值，否則清成空字串
    return fallback === undefined ? '' : fallback;
  });
}

/**
 * 把 <block src="..."> 轉成區塊檔名。
 * 讓初學者不用煩惱相對路徑：
 *   "navbar.html"            → navbar.html
 *   "navbar"                 → navbar.html
 *   "../blocks/navbar.html"  → navbar.html（取 basename）
 *   "partials\\nav.html"     → nav.html（Windows 斜線也支援）
 */
export function toBlockFileName(rawSrc) {
  let name = String(rawSrc ?? '').trim().replace(/\\/g, '/');
  name = name.split('/').filter(Boolean).pop() ?? '';
  if (!name) return '';
  if (!/\.html$/i.test(name)) name += '.html';
  return name;
}

/** 取出元素在原始碼中的「內部」字串（保持使用者原始排版） */
function extractInnerSource(element, source) {
  const children = element.childNodes ?? [];
  if (children.length === 0) return '';

  const first = children[0]?.range?.[0];
  const last = children[children.length - 1]?.range?.[1];
  if (typeof first !== 'number' || typeof last !== 'number' || last < first) {
    return element.innerHTML ?? '';
  }
  return source.slice(first, last);
}

/**
 * 讀取來源檔案。
 * 特別處理 UTF-8 BOM（\uFEFF）：
 *  有些編輯器（Windows 记事本、部分 VS Code 設定）會存成帶 BOM 的 UTF-8，
 *  如果不處理，BOM 會被塞進組裝結果的中間位置（例如區塊展開的地方），造成頁面出現隱形的怪字元。
 */
export function readSourceFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  return content.charCodeAt(0) === 0xfeff ? content.slice(1) : content;
}

/**
 * 檢查一個起始標籤，回傳它的結束位置與是否為自閉合寫法。
 *
 * 以字元掃描（不使用 Regex）逐一走過屬性值，正確找到對應的 '>'：
 *   <block src="a.html" />   → { end: ..., selfClosing: true }
 *   <block src="a.html">     → { end: ..., selfClosing: false }
 *   <block title="a>b">      → 屬性值裡的 '>' 不會被誤判
 */
function inspectStartTag(source, start) {
  let index = start + 1;
  let quote = null;

  while (index < source.length) {
    const char = source[index];

    if (quote) {
      if (char === quote) quote = null;
    } else if (char === '"' || char === "'") {
      quote = char;
    } else if (char === '>') {
      let cursor = index - 1;
      while (cursor > start && /\s/.test(source[cursor])) cursor -= 1;
      return { end: index + 1, selfClosing: source[cursor] === '/' };
    }

    index += 1;
  }

  return { end: source.length, selfClosing: false };
}

/**
 * 「嚴格語法規範」掃描器：找出所有不合法的 <block> 寫法。
 *
 * 為什麼需要掃描原始碼？
 *   node-html-parser 對「未閉合」的 <block ...> 會直接把它從 DOM 裡丟掉
 *   （元素根本不存在），對「自閉合」的 <block ... /> 則會保留成一個空元素。
 *   這兩種寫法都不會報錯，只會讓區塊「無聲地消失」或產生歧義，
 *   因此語法檢查必須回到原始碼層級才能察覺。
 *
 * ⚠ 這裡只是「語法檢查」；真正的區塊展開 100% 仍由 DOM/AST 驅動（見 expandHtml）。
 * ⚠ HTML 註解裡的內容會被跳過，不會被誤判成語法錯誤。
 *
 * @returns {Array<{kind: 'self-closing'|'unclosed'|'stray-end', start: number, end: number}>}
 */
export function scanBlockSyntax(source) {
  const lower = source.toLowerCase();
  const tokens = [];
  let index = 0;

  while (index < source.length) {
    const next = lower.indexOf('<', index);
    if (next === -1) break;

    // 跳過 HTML 註解 <!-- ... -->
    if (lower.startsWith('<!--', next)) {
      const close = lower.indexOf('-->', next + 4);
      index = close === -1 ? source.length : close + 3;
      continue;
    }

    // <block ...> 起始標籤
    if (lower.startsWith('<block', next)) {
      const after = source[next + 6];
      if (after && !/[\s/>]/.test(after)) {
        index = next + 6;
        continue;
      }
      const { end, selfClosing } = inspectStartTag(source, next);
      tokens.push({ type: 'start', start: next, end, selfClosing });
      index = end;
      continue;
    }

    // </block> 結束標籤
    if (lower.startsWith('</block', next)) {
      const after = source[next + 7];
      if (after && !/[\s>]/.test(after)) {
        index = next + 7;
        continue;
      }
      const close = source.indexOf('>', next);
      const end = close === -1 ? source.length : close + 1;
      tokens.push({ type: 'end', start: next, end });
      index = end;
      continue;
    }

    index = next + 1;
  }

  // 配對：起始標籤與結束標籤
  const openStack = [];
  const issues = [];

  for (const token of tokens) {
    if (token.type === 'start') {
      if (token.selfClosing) {
        issues.push({ kind: 'self-closing', start: token.start, end: token.end });
        continue;
      }
      openStack.push(token);
      continue;
    }

    if (openStack.pop() === undefined) {
      issues.push({ kind: 'stray-end', start: token.start, end: token.end });
    }
  }

  // 留在堆疊裡的就是沒有配對到結束標籤的起始標籤
  for (const orphan of openStack) {
    issues.push({ kind: 'unclosed', start: orphan.start, end: orphan.end });
  }

  return issues;
}

/** 嚴格語法錯誤的提示訊息與錯誤框 */
function syntaxError(issue) {
  const hint = '&lt;block src="..."&gt;&lt;/block&gt;';

  switch (issue.kind) {
    case 'self-closing':
      return {
        message: '<block> 不支援自閉合 /> 寫法，請使用完整的 <block src="..."></block>。',
        replacement: errorBox(
          '[ERROR: block 不支援自閉合]',
          '<block> 不支援自閉合 /> 寫法',
          `請使用完整的 ${hint}。`,
        ),
      };
    case 'unclosed':
      return {
        message: '<block> 缺少結束標籤 </block>，請使用完整的 <block src="..."></block>。',
        replacement: errorBox(
          '[ERROR: block 缺少結束標籤]',
          '<block> 缺少結束標籤 </block>',
          `請使用完整的 ${hint}。`,
        ),
      };
    default:
      return {
        message: '有多餘的 </block> 結束標籤，沒有可以配對的 <block> 起始標籤。',
        replacement: errorBox(
          '[ERROR: 多餘的 </block> 結束標籤]',
          '多餘的 </block> 結束標籤',
          '請確認 <block> 標籤是否成對出現。',
        ),
      };
  }
}

/** 統一解析 HTML：node-html-parser v7（DOM/AST） */
function parseHtml(html) {
  return parse(html, {
    comment: true,
    blockTextElements: { script: true, noscript: true, style: true, pre: true },
  });
}

/** 錯誤提示框（醒目、但不會讓整個建置中斷） */
function errorBox(comment, headline, detail) {
  return [
    `<!-- ${comment} -->`,
    '<div style="border:2px solid #dc2626;background:#fef2f2;color:#b91c1c;padding:12px 16px;',
    'border-radius:8px;font-family:system-ui,-apple-system,sans-serif;margin:8px 0;">',
    `<strong>⚠️ ${headline}</strong><br>`,
    detail,
    '</div>',
  ].join('');
}

/* ------------------------------------------------------------------ *
 * 核心：展開 <block> 標籤
 * ------------------------------------------------------------------ */

/**
 * 把一段 HTML 裡的所有 <block> 標籤展開。
 * @param {string} html
 * @param {object} context
 * @returns {{ html: string, errors: Array<{message: string}> }}
 */
export function expandHtml(html, context) {
  const root = parseHtml(html);
  const blockElements = root.querySelectorAll(BLOCK_TAG);
  const syntaxIssues = scanBlockSyntax(html);
  if (blockElements.length === 0 && syntaxIssues.length === 0) {
    return { html, errors: [] };
  }

  const errors = [];

  // ── 待替換的區域 ──
  //   region.start / region.end 一律是「相對於這份不可變原始碼」的位移。
  //   priority：語法錯誤優先（同一個位置若同時有語法錯誤與 DOM 元素，以語法錯誤為準，
  //   這樣自閉合的 <block /> 才會被當成錯誤，而不是被正常展開）。
  const regions = [];

  // (1) 嚴格語法檢查：自閉合 / 未閉合 / 多餘結束標籤
  for (const issue of syntaxIssues) {
    const { replacement, message } = syntaxError(issue);
    context.logger.error(message);
    errors.push({ message });
    regions.push({ start: issue.start, end: issue.end, replacement, priority: 0 });
  }

  // (2) 正常區塊的展開（DOM/AST 驅動）
  for (const element of blockElements) {
    const [start, end] = element.range ?? [];
    if (typeof start !== 'number' || typeof end !== 'number') continue;
    regions.push({ start, end, element, priority: 1 });
  }

  regions.sort((a, b) => a.start - b.start || a.priority - b.priority);

  // ⚠ 位移安全說明（多個同層 <block> 的替換）：
  //   這裡不是「就地修改字串」，而是「單次前向掃描 + 片段陣列拼接」。
  //   關鍵在於迴圈內的 `html` 從頭到尾都是同一份「不可變」的原始碼：
  //     - region 的 [start, end] 永遠是相對於這份原始碼的位移，
  //       因此前一個區塊展開後字串長度改變，不會影響後續區塊的位移。
  //     - 展開結果是另外產生的 replacement 字串，寫進 pieces，不會回寫 html。
  //     - cursor 記住上一個區域的結束位置，確保片段不重疊、不遺漏、不重複。
  //   （等價於「由後往前替換」的保證效果，但只解析一次、只掃描一次。）
  const pieces = [];
  let cursor = 0;

  for (const region of regions) {
    // 巢狀的 <block> 由外層展開時遞迴處理，這裡跳過以免重複替換
    if (region.start < cursor) continue;

    let replacement = region.replacement;

    if (region.element) {
      const built = buildBlock(region.element, html, context);
      replacement = built.replacement;
      errors.push(...built.errors);
    }

    pieces.push(html.slice(cursor, region.start), replacement);
    cursor = region.end;
  }

  pieces.push(html.slice(cursor));
  return { html: pieces.join(''), errors };
}

/**
 * 處理單一 <block> 標籤，產生要替換進去的字串。
 */
function buildBlock(element, source, context) {
  const rawSrc = (element.getAttribute('src') ?? '').trim();

  // 取得 <block> 上除了 src 以外的所有屬性（屬性名稱一律小寫化，HTML 屬性不區分大小寫）
  const attributes = {};
  for (const [key, value] of Object.entries(element.attributes ?? {})) {
    attributes[key.toLowerCase()] = value;
  }
  delete attributes.src;

  // <block> 內部的原始碼 = 插槽（slot）內容
  const innerSource = extractInnerSource(element, source);
  const hasSlotContent = innerSource.trim().length > 0;

  if (!rawSrc) {
    const message = '<block> 標籤缺少 src 屬性，無法找到對應的區塊檔案。';
    context.logger.error(message);
    return {
      replacement: errorBox('[ERROR: block 缺少 src 屬性]', '區塊缺少 src 屬性', message),
      errors: [{ message, src: '' }],
    };
  }

  const fileName = toBlockFileName(rawSrc);
  const blockFile = path.join(context.blocksDir, fileName);

  if (!fileName || !fs.existsSync(blockFile) || !fs.statSync(blockFile).isFile()) {
    const message = `找不到區塊 ${fileName || rawSrc}（預期路徑：${relLabel(blockFile, context.cwd)}）。`;
    context.logger.error(message);
    return {
      replacement: errorBox(
        `[ERROR: 找不到區塊 ${fileName || rawSrc}]`,
        `找不到區塊 ${fileName || rawSrc}`,
        `請確認 <code>${relLabel(blockFile, context.cwd)}</code> 是否存在，或檢查 <code>src</code> 屬性是否寫對。`,
      ),
      errors: [{ message, src: rawSrc }],
    };
  }

  // ── 循環引用防護：沿著呼叫鏈追蹤 ──
  const loopIndex = context.chain.indexOf(blockFile);
  if (loopIndex !== -1) {
    const loopPath = [...context.chain.slice(loopIndex), blockFile]
      .map((item) => path.basename(item))
      .join(' → ');
    const message = `偵測到循環引用：${loopPath}。已中止這個區塊的展開，避免無限迴圈。`;
    context.logger.error(message);
    return {
      replacement: errorBox(
        `[ERROR: 循環引用 ${loopPath}]`,
        '偵測到循環引用',
        `呼叫鏈：<code>${loopPath}</code>。請移除其中一個重複的區塊引用。`,
      ),
      errors: [{ message, src: rawSrc }],
    };
  }

  // ── 遞迴展開區塊內容（區塊內可以再引用其他區塊）──
  const blockSource = readSourceFile(blockFile);
  const childContext = { ...context, chain: [...context.chain, blockFile] };
  const expanded = expandHtml(blockSource, childContext);
  const errors = [...expanded.errors];

  // ── 插槽內容：先解析內層的 <block>，再塞回 <slot> ──
  let slotContent = '';
  if (hasSlotContent) {
    const innerResult = expandHtml(innerSource, context);
    slotContent = innerResult.html;
    errors.push(...innerResult.errors);
  }

  const label = relLabel(blockFile, context.cwd, `blocks/${path.basename(blockFile)}`);

  // ── 套用 slot（預設內容 vs 傳入內容）──
  let content = applySlots(expanded.html, slotContent, hasSlotContent, label, context);

  // ── 屬性參數插值 {{key}} / {{key | 預設文字}} ──
  content = interpolate(content, attributes);

  const replacement = context.comments
    ? `<!-- [BLOCK START: ${label}] -->\n${content}\n<!-- [BLOCK END: ${label}] -->`
    : content;

  return { replacement, errors };
}

/**
 * 處理 <slot> 插槽：
 *  - 有傳入子節點 → 用傳入內容取代整個 <slot> 標籤
 *  - 沒有傳入     → 保留 <slot> 內的預設內容（沒有預設內容就整個移除）
 */
function applySlots(blockHtml, slotContent, hasSlotContent, label, context) {
  const root = parseHtml(blockHtml);
  const slots = root.querySelectorAll(SLOT_TAG);
  if (slots.length === 0) {
    if (hasSlotContent) {
      context.logger.warn(
        `區塊 ${label} 裡沒有 <slot> 插槽，<block> 內傳入的內容將被忽略。`,
      );
    }
    return blockHtml;
  }

  const pieces = [];
  let cursor = 0;

  for (const slot of slots) {
    const [start, end] = slot.range ?? [];
    if (typeof start !== 'number' || typeof end !== 'number') continue;
    if (start < cursor) continue;

    const defaultContent = extractInnerSource(slot, blockHtml);
    const replacement = hasSlotContent ? slotContent : defaultContent;

    pieces.push(blockHtml.slice(cursor, start), replacement);
    cursor = end;
  }

  pieces.push(blockHtml.slice(cursor));
  return pieces.join('');
}

/* ------------------------------------------------------------------ *
 * 單層平鋪掃描
 * ------------------------------------------------------------------ */

/**
 * 掃描一個目錄，只取第一層的 .html 檔案。
 * 子目錄會被回報出來（交由呼叫端印出黃色警告並跳過）。
 */
export function scanFlatDirectory(directory) {
  const files = [];
  const subDirectories = [];

  if (!fs.existsSync(directory)) return { files, subDirectories };

  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      subDirectories.push(fullPath);
      continue;
    }
    if (entry.isFile() && entry.name.toLowerCase().endsWith('.html')) {
      files.push(fullPath);
    }
  }

  files.sort((a, b) => a.localeCompare(b));
  return { files, subDirectories };
}

/* ------------------------------------------------------------------ *
 * 對外 API
 * ------------------------------------------------------------------ */

/**
 * 編譯單一頁面，回傳組裝後的 HTML 字串（不寫檔）。
 * @returns {{ html: string, errors: Array<{message: string}> }}
 */
export function compileHtml(source, options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const srcDir = resolveDir(options.srcDir ?? 'src', cwd);
  const logger = options.logger ?? createLogger({ silent: true });

  const context = {
    cwd,
    srcDir,
    blocksDir: path.join(srcDir, 'blocks'),
    comments: options.comments !== false,
    logger,
    chain: [],
  };

  const expanded = expandHtml(source, context);
  // 最終清理：沒有屬性、也沒有預設值的 {{...}} 一律清成空字串
  const cleaned = interpolate(expanded.html, {});
  return { html: cleaned, errors: expanded.errors };
}

/**
 * 編譯單一頁面並寫入輸出目錄（同名 .html 單點覆寫）。
 */
export function compilePage(options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const srcDir = resolveDir(options.srcDir ?? 'src', cwd);
  const outDir = resolveDir(options.outDir ?? '.', cwd);
  const comments = options.comments !== false;
  const logger = options.logger ?? createLogger();

  const pageFile = path.resolve(cwd, options.pageFile);
  const source = readSourceFile(pageFile);

  const context = {
    cwd,
    srcDir,
    blocksDir: path.join(srcDir, 'blocks'),
    comments,
    logger,
    chain: [],
  };

  const expanded = expandHtml(source, context);
  const cleaned = interpolate(expanded.html, {});

  const pageLabel = relLabel(pageFile, cwd, `src/pages/${path.basename(pageFile)}`);
  const output = `${warningComment(pageLabel)}\n${cleaned}\n`;

  // 安全鐵律：只寫出這一個檔案，絕對不清空輸出目錄
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, path.basename(pageFile));
  fs.writeFileSync(outFile, output, 'utf8');

  return {
    pageFile,
    outFile,
    outLabel: relLabel(outFile, cwd, path.basename(outFile)),
    errors: expanded.errors,
    bytes: Buffer.byteLength(output, 'utf8'),
  };
}

/**
 * 編譯整個專案：src/pages/*.html → 輸出目錄。
 * @returns {{ count: number, files: Array, errors: Array, durationMs: number }}
 */
export function buildProject(options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const srcDir = resolveDir(options.srcDir ?? 'src', cwd);
  const outDir = resolveDir(options.outDir ?? '.', cwd);
  const comments = options.comments !== false;
  const logger = options.logger ?? createLogger();

  const startedAt = performance.now();
  const pagesDir = path.join(srcDir, 'pages');
  const blocksDir = path.join(srcDir, 'blocks');

  const pages = scanFlatDirectory(pagesDir);
  const blocks = scanFlatDirectory(blocksDir);

  // ── 防呆檢查：只支援單層平鋪檔案 ──
  for (const subDirectory of [...pages.subDirectories, ...blocks.subDirectories]) {
    logger.warn(
      `為避免路徑混亂，本工具僅支援單層平鋪檔案，已忽略子目錄：${relLabel(subDirectory, cwd)}`,
    );
  }

  if (pages.files.length === 0) {
    logger.warn(`在 ${relLabel(pagesDir, cwd, 'src/pages')} 找不到任何 .html 頁面檔案。`);
  }

  const files = [];
  const errors = [];

  for (const pageFile of pages.files) {
    const result = compilePage({
      cwd,
      srcDir,
      outDir,
      comments,
      logger,
      pageFile,
    });
    files.push(result);
    errors.push(...result.errors);
    logger.success(`已輸出 ${result.outLabel}（${formatBytes(result.bytes)}）`);
  }

  const durationMs = performance.now() - startedAt;
  return { count: files.length, files, errors, durationMs, srcDir, outDir };
}

/** 把位元組數轉成人類看得懂的格式 */
export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}
