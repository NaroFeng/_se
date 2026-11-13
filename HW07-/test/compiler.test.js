/**
 * test/compiler.test.js
 * ---------------------------------------------------------------
 * 使用 Node.js 內建 test runner（node --test）驗證核心編譯引擎。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  buildProject,
  compileHtml,
  compilePage,
  interpolate,
  toBlockFileName,
  warningComment,
} from '../lib/compiler.js';
import { createLogger } from '../lib/logger.js';

const silentLogger = createLogger({ silent: true });

/** 建立一個暫存專案，回傳 { root, writeBlock, writePage } */
function createProject(files = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'html-block-test-'));
  for (const [relativePath, content] of Object.entries(files)) {
    const target = path.join(root, relativePath);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, content, 'utf8');
  }
  return {
    root,
    write(relativePath, content) {
      const target = path.join(root, relativePath);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, content, 'utf8');
    },
    cleanup() {
      fs.rmSync(root, { recursive: true, force: true });
    },
  };
}

/* ------------------------------------------------------------------ *
 * 純函式
 * ------------------------------------------------------------------ */

test('interpolate：{{key}} 取屬性值，沒有就清成空字串', () => {
  assert.equal(interpolate('Hello {{name}}!', { name: '小明' }), 'Hello 小明!');
  assert.equal(interpolate('Hello {{name}}!', {}), 'Hello !');
  assert.equal(interpolate('{{a}}{{b}}', { a: '1' }), '1');
});

test('interpolate：{{key | 預設文字}} 支援預設值', () => {
  assert.equal(interpolate('{{title | 未命名}}', { title: '首頁' }), '首頁');
  assert.equal(interpolate('{{title | 未命名}}', {}), '未命名');
  assert.equal(interpolate('{{title | 未命名}}', { title: '' }), '');
});

test('interpolate：佔位符前後空白不影響解析', () => {
  assert.equal(interpolate('{{ name }}', { name: 'OK' }), 'OK');
  assert.equal(interpolate('{{ name | 預設 }}', {}), '預設');
});

test('toBlockFileName：支援省略副檔名與相對路徑', () => {
  assert.equal(toBlockFileName('navbar.html'), 'navbar.html');
  assert.equal(toBlockFileName('navbar'), 'navbar.html');
  assert.equal(toBlockFileName('../blocks/navbar.html'), 'navbar.html');
  assert.equal(toBlockFileName('./navbar'), 'navbar.html');
  assert.equal(toBlockFileName('partials\\card.html'), 'card.html');
  assert.equal(toBlockFileName('  '), '');
});

/* ------------------------------------------------------------------ *
 * 編譯行為
 * ------------------------------------------------------------------ */

test('基本組裝：區塊展開 + 屬性插值 + 插槽', () => {
  const project = createProject({
    'src/blocks/navbar.html': '<nav>{{title}}</nav>',
    'src/blocks/card.html': '<article>{{title | 無題}}<slot>預設</slot></article>',
  });

  try {
    const result = compileHtml(
      '<block src="navbar.html" title="首頁"></block>' +
        '<block src="card.html" title="A"><p>自訂</p></block>' +
        '<block src="card.html"></block>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 0);
    assert.match(result.html, /<nav>首頁<\/nav>/);
    assert.match(result.html, /<article>A<p>自訂<\/p><\/article>/);
    // 沒有傳插槽內容 → 保留預設內容
    assert.match(result.html, /<article>無題預設<\/article>/);
  } finally {
    project.cleanup();
  }
});

test('區塊邊界註解：預設開啟，--no-comments 可關閉', () => {
  const project = createProject({ 'src/blocks/navbar.html': '<nav>x</nav>' });

  try {
    const withComments = compileHtml('<block src="navbar.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });
    assert.match(withComments.html, /<!-- \[BLOCK START: src\/blocks\/navbar\.html\] -->/);
    assert.match(withComments.html, /<!-- \[BLOCK END: src\/blocks\/navbar\.html\] -->/);

    const withoutComments = compileHtml('<block src="navbar.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      comments: false,
      logger: silentLogger,
    });
    assert.doesNotMatch(withoutComments.html, /BLOCK START/);
    assert.doesNotMatch(withoutComments.html, /BLOCK END/);
  } finally {
    project.cleanup();
  }
});

test('找不到區塊：不會崩潰，改成錯誤提示框', () => {
  const project = createProject();

  try {
    const result = compileHtml('<block src="nope.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });

    assert.equal(result.errors.length, 1);
    assert.match(result.html, /\[ERROR: 找不到區塊 nope\.html\]/);
    assert.match(result.html, /找不到區塊 nope\.html/);
  } finally {
    project.cleanup();
  }
});

test('循環引用：被攔截並回報中文錯誤', () => {
  const project = createProject({
    'src/blocks/a.html': '<div>A<block src="b.html"></block></div>',
    'src/blocks/b.html': '<div>B<block src="a.html"></block></div>',
  });

  try {
    const result = compileHtml('<block src="a.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });

    assert.ok(result.errors.length >= 1);
    assert.match(result.errors[0].message, /循環引用/);
    assert.match(result.html, /\[ERROR: 循環引用/);
  } finally {
    project.cleanup();
  }
});

test('巢狀引用：區塊可以互相引用（無循環時）', () => {
  const project = createProject({
    'src/blocks/outer.html': '<main><block src="inner.html"></block></main>',
    'src/blocks/inner.html': '<span>inner</span>',
  });

  try {
    const result = compileHtml('<block src="outer.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });

    assert.equal(result.errors.length, 0);
    // 巢狀區塊會各自帶上自己的邊界註解
    assert.match(result.html, /<!-- \[BLOCK START: src\/blocks\/inner\.html\] -->/);
    assert.match(result.html, /<span>inner<\/span>/);
    assert.match(result.html, /<!-- \[BLOCK END: src\/blocks\/outer\.html\] -->/);
  } finally {
    project.cleanup();
  }
});

test('未傳入且無預設值的佔位符最終清成空字串', () => {
  const project = createProject({ 'src/blocks/navbar.html': '<nav>{{title}}</nav>' });

  try {
    const result = compileHtml('<block src="navbar.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });
    assert.match(result.html, /<nav><\/nav>/);
    assert.doesNotMatch(result.html, /\{\{/);
  } finally {
    project.cleanup();
  }
});

test('頁面層級的佔位符：無屬性來源時使用預設值', () => {
  const project = createProject();

  try {
    const result = compileHtml('<title>{{title | 我的網站}}</title>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });
    assert.match(result.html, /<title>我的網站<\/title>/);
  } finally {
    project.cleanup();
  }
});

/* ------------------------------------------------------------------ *
 * 多同層 <block> 的位移安全（el.range 替換）
 * ------------------------------------------------------------------ */

test('多同層 block：前一個區塊展開後長度大變，不會錯亂後續區塊的位移', () => {
  // 故意讓三個區塊的「展開前後長度差異」非常大：
  //   big  → 展開後暴增 500 個字元
  //   tiny → 展開後縮減成 3 個字元
  //   mid  → 展開後長度居中
  const project = createProject({
    'src/blocks/big.html': `<div>${'A'.repeat(500)}</div>`,
    'src/blocks/tiny.html': '<i>x</i>',
    'src/blocks/mid.html': `<p>${'B'.repeat(50)}</p>`,
  });

  try {
    const result = compileHtml(
      '<p>前段</p><block src="big.html"></block><p>中段</p>' +
        '<block src="tiny.html"></block><p>後段</p>' +
        '<block src="mid.html"></block><p>結尾</p>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 0);

    // 每個區塊的內容都要出現，而且順序正確
    const bigIndex = result.html.indexOf('A'.repeat(500));
    const tinyIndex = result.html.indexOf('<i>x</i>');
    const midIndex = result.html.indexOf('B'.repeat(50));

    assert.ok(bigIndex > -1, 'big 區塊應該有展開');
    assert.ok(tinyIndex > -1, 'tiny 區塊應該有展開');
    assert.ok(midIndex > -1, 'mid 區塊應該有展開');
    assert.ok(bigIndex < tinyIndex, 'big 應該在 tiny 之前');
    assert.ok(tinyIndex < midIndex, 'tiny 應該在 mid 之前');

    // 區塊之間的靜態文字都必須完整保留（沒有被吃掉或重複）
    assert.match(result.html, /<p>前段<\/p>/);
    assert.match(result.html, /<p>中段<\/p>/);
    assert.match(result.html, /<p>後段<\/p>/);
    assert.match(result.html, /<p>結尾<\/p>/);
    assert.equal(result.html.match(/<p>前段<\/p>/g).length, 1);
    assert.equal(result.html.match(/<p>結尾<\/p>/g).length, 1);

    // 沒有重複或遺漏的區塊邊界註解
    assert.equal((result.html.match(/BLOCK START/g) ?? []).length, 3);
    assert.equal((result.html.match(/BLOCK END/g) ?? []).length, 3);
  } finally {
    project.cleanup();
  }
});

test('多同層 block：巢狀區塊不會被重複替換', () => {
  const project = createProject({
    'src/blocks/outer.html': '<div><block src="inner.html"></block></div>',
    'src/blocks/inner.html': '<span>INNER</span>',
  });

  try {
    const result = compileHtml(
      '<block src="outer.html"></block><block src="inner.html"></block>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 0);
    // 巢狀的 inner 只應該展開一次（外層一次 + 頁面直接引用一次 = 2 次）
    assert.equal((result.html.match(/<span>INNER<\/span>/g) ?? []).length, 2);
    assert.equal((result.html.match(/BLOCK START/g) ?? []).length, 3);
  } finally {
    project.cleanup();
  }
});

/* ------------------------------------------------------------------ *
 * 嚴格語法規範：<block> 必須成對閉合
 * ------------------------------------------------------------------ */

test('嚴格語法：自閉合 <block /> 視為語法錯誤，且不會吞掉後面的內容', () => {
  const project = createProject({ 'src/blocks/nav.html': '<nav>NAV</nav>' });

  try {
    const result = compileHtml(
      '<p>前段</p><block src="nav.html" /><p>後段</p>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0].message, /不支援自閉合/);
    assert.match(result.errors[0].message, /<block src="\.\.\."><\/block>/);
    assert.match(result.html, /\[ERROR: block 不支援自閉合/);

    // ★ 重點：後面的頁面內容不能被當成 slot 吞掉
    assert.match(result.html, /<p>前段<\/p>/);
    assert.match(result.html, /<p>後段<\/p>/);

    // 語法錯誤的區塊不應該被展開
    assert.doesNotMatch(result.html, /<nav>NAV<\/nav>/);
  } finally {
    project.cleanup();
  }
});

test('嚴格語法：未閉合的 <block> 視為語法錯誤，且不會吞掉後面的內容', () => {
  const project = createProject({ 'src/blocks/nav.html': '<nav>NAV</nav>' });

  try {
    const result = compileHtml(
      '<p>前段</p><block src="nav.html"><p>後段</p>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0].message, /缺少結束標籤/);
    assert.match(result.html, /\[ERROR: block 缺少結束標籤/);

    // ★ 重點：後面的頁面內容必須完整保留
    assert.match(result.html, /<p>前段<\/p>/);
    assert.match(result.html, /<p>後段<\/p>/);
    assert.doesNotMatch(result.html, /<nav>NAV<\/nav>/);
  } finally {
    project.cleanup();
  }
});

test('嚴格語法：多餘的 </block> 結束標籤會被偵測', () => {
  const project = createProject();

  try {
    const result = compileHtml('<p>內容</p></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });

    assert.equal(result.errors.length, 1);
    assert.match(result.errors[0].message, /多餘的 <\/block>/);
    assert.match(result.html, /\[ERROR: 多餘的 <\/block>/);
    assert.match(result.html, /<p>內容<\/p>/);
  } finally {
    project.cleanup();
  }
});

test('嚴格語法：HTML 註解裡的 <block /> 不會被誤判成語法錯誤', () => {
  const project = createProject({ 'src/blocks/nav.html': '<nav>NAV</nav>' });

  try {
    const result = compileHtml(
      '<!-- <block src="nav.html" /> 這是註解 --><block src="nav.html"></block>',
      { cwd: project.root, srcDir: 'src', logger: silentLogger },
    );

    assert.equal(result.errors.length, 0);
    assert.match(result.html, /<nav>NAV<\/nav>/);
  } finally {
    project.cleanup();
  }
});

test('嚴格語法：巢狀 <block> 正常配對時不會誤報', () => {
  const project = createProject({
    'src/blocks/outer.html': '<div><block src="inner.html"></block></div>',
    'src/blocks/inner.html': '<span>INNER</span>',
  });

  try {
    const result = compileHtml('<block src="outer.html"></block>', {
      cwd: project.root,
      srcDir: 'src',
      logger: silentLogger,
    });

    assert.equal(result.errors.length, 0);
    assert.match(result.html, /<span>INNER<\/span>/);
  } finally {
    project.cleanup();
  }
});

/* ------------------------------------------------------------------ *
 * buildProject
 * ------------------------------------------------------------------ */

test('build：輸出檔案第一行一定是防呆警告註解', () => {
  const project = createProject({
    'src/pages/index.html': '<h1>hi</h1>',
  });

  try {
    const result = buildProject({
      cwd: project.root,
      srcDir: 'src',
      outDir: '.',
      logger: silentLogger,
    });

    assert.equal(result.count, 1);
    const output = fs.readFileSync(path.join(project.root, 'index.html'), 'utf8');
    assert.ok(output.startsWith(warningComment('src/pages/index.html')));
    assert.equal(output.split('\n')[0], warningComment('src/pages/index.html'));
  } finally {
    project.cleanup();
  }
});

test('build：絕對不會刪除輸出目錄裡既有的檔案', () => {
  const project = createProject({
    'src/pages/index.html': '<h1>hi</h1>',
    'keep-me.txt': '重要資料',
    'images/pic.jpg': 'fake-image',
  });

  try {
    buildProject({ cwd: project.root, srcDir: 'src', outDir: '.', logger: silentLogger });

    assert.ok(fs.existsSync(path.join(project.root, 'keep-me.txt')));
    assert.ok(fs.existsSync(path.join(project.root, 'images/pic.jpg')));
    assert.equal(fs.readFileSync(path.join(project.root, 'keep-me.txt'), 'utf8'), '重要資料');
  } finally {
    project.cleanup();
  }
});

test('build：只輸出 src/pages 底下的同名 .html（單點覆寫）', () => {
  const project = createProject({
    'src/pages/index.html': '<h1>index</h1>',
    'src/pages/about.html': '<h1>about</h1>',
    'src/blocks/nav.html': '<nav></nav>',
  });

  try {
    buildProject({ cwd: project.root, srcDir: 'src', outDir: '.', logger: silentLogger });

    assert.ok(fs.existsSync(path.join(project.root, 'index.html')));
    assert.ok(fs.existsSync(path.join(project.root, 'about.html')));
    // 區塊檔案不應該被輸出到根目錄
    assert.ok(!fs.existsSync(path.join(project.root, 'nav.html')));
  } finally {
    project.cleanup();
  }
});

test('build：子目錄會被忽略並印出警告（單層平鋪約束）', () => {
  const project = createProject({
    'src/pages/index.html': '<h1>index</h1>',
    'src/pages/extra/page.html': '<h1>extra</h1>',
    'src/blocks/nested/thing.html': '<div></div>',
  });

  const warnings = [];
  const logger = {
    ...silentLogger,
    warn: (message) => warnings.push(message),
  };

  try {
    buildProject({ cwd: project.root, srcDir: 'src', outDir: '.', logger });

    assert.equal(warnings.length, 2);
    assert.ok(warnings.some((w) => w.includes('僅支援單層平鋪檔案')));
    assert.ok(warnings.some((w) => w.includes('已忽略子目錄')));
    assert.ok(warnings.some((w) => w.includes('extra')));

    // 子目錄裡的頁面不會被編譯
    assert.ok(!fs.existsSync(path.join(project.root, 'page.html')));
  } finally {
    project.cleanup();
  }
});

test('compilePage：輸出到自訂的 out 目錄', () => {
  const project = createProject({ 'src/pages/index.html': '<h1>hi</h1>' });

  try {
    const result = compilePage({
      cwd: project.root,
      srcDir: 'src',
      outDir: 'dist',
      pageFile: path.join(project.root, 'src/pages/index.html'),
      logger: silentLogger,
    });

    assert.equal(result.outFile, path.join(project.root, 'dist', 'index.html'));
    assert.ok(fs.existsSync(result.outFile));
  } finally {
    project.cleanup();
  }
});

test('來源檔案帶 UTF-8 BOM 時，BOM 不會滲入組裝結果', () => {
  const project = createProject({
    'src/blocks/nav.html': '\uFEFF<nav>BOM</nav>',
  });
  // 用帶 BOM 的位元組寫入頁面來源檔
  fs.mkdirSync(path.join(project.root, 'src/pages'), { recursive: true });
  fs.writeFileSync(
    path.join(project.root, 'src/pages/index.html'),
    Buffer.concat([
      Buffer.from([0xef, 0xbb, 0xbf]),
      Buffer.from('<block src="nav.html"></block>', 'utf8'),
    ]),
  );

  try {
    const result = compilePage({
      cwd: project.root,
      srcDir: 'src',
      outDir: '.',
      pageFile: path.join(project.root, 'src/pages/index.html'),
      logger: silentLogger,
    });

    const output = fs.readFileSync(result.outFile, 'utf8');
    assert.equal(output.split('\uFEFF').length - 1, 0, '輸出不應該含有 BOM 字元');
    assert.ok(output.startsWith(warningComment('src/pages/index.html')));
    assert.match(output, /<nav>BOM<\/nav>/);
  } finally {
    project.cleanup();
  }
});
