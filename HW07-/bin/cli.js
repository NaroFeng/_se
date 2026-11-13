#!/usr/bin/env node
/**
 * bin/cli.js
 * ---------------------------------------------------------------
 * html-block-assembler 命令列介面
 *
 *   npx html-block init
 *   npx html-block build [--src <dir>] [--out <dir>] [--no-comments]
 *   npx html-block watch [--src <dir>] [--out <dir>]
 */
import fs from 'node:fs';
import process from 'node:process';
import { parseArgs } from 'node:util';
import pc from 'picocolors';
import { buildProject } from '../lib/compiler.js';
import { initProject } from '../lib/init.js';
import { watchProject } from '../lib/watcher.js';
import { createLogger } from '../lib/logger.js';

const PACKAGE = JSON.parse(
  fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
);

const HELP = `
${pc.bold(pc.cyan('html-block'))} ${pc.dim(`v${PACKAGE.version}`)} — 建置期 HTML 區塊組裝器（專為 HTML 初學者設計）

${pc.bold('用法')}
  npx html-block <指令> [選項]

${pc.bold('指令')}
  init     在當前目錄建立標準範例結構（src/pages、src/blocks、css）
  build    把 src/pages/*.html 組裝成完整網頁，輸出到專案根目錄
  watch    組裝一次之後，持續監聽 src/ 的變更並自動重新組裝

${pc.bold('選項')}
  --src <dir>     來源目錄（預設：./src）
  --out <dir>     輸出目錄（預設：./，也就是專案根目錄）
  --no-comments   不產生 [BLOCK START/END] 區塊邊界註解
  -h, --help      顯示這份說明
  -v, --version   顯示版本號碼

${pc.bold('範例')}
  ${pc.dim('# 一鍵建立範例並組裝')}
  npx html-block init
  npx html-block build

  ${pc.dim('# 輸出到別的資料夾，並且不要區塊邊界註解')}
  npx html-block build --out dist --no-comments
`;

/**
 * Node 內建的 util.parseArgs 不支援 `--no-xxx` 這種否定式語法，
 * 所以先自己把 `--no-comments` 攔下來處理，再交給 parseArgs 解析其他參數。
 */
function preprocessArgs(argv) {
  let noComments = false;
  const rest = [];

  for (const arg of argv) {
    if (arg === '--no-comments') {
      noComments = true;
      continue;
    }
    rest.push(arg);
  }

  return { argv: rest, noComments };
}

function parseCliArgs(argv) {
  // util.parseArgs 是 Node.js v18.3.0 之後才提供的 API。
  // 雖然 package.json 宣告 engines >= 18.0.0，但 v18.0 ~ v18.2 實際上沒有這個函式，
  // 與其讓使用者看到看不懂的 TypeError，不如直接給一句清楚的升級提示。
  if (typeof parseArgs !== 'function') {
    console.error(
      `${pc.red('✖')} 目前的 Node.js 版本（${process.version}）太舊，` +
        `請升級到 Node.js v18.3.0 以上再使用 html-block。`,
    );
    process.exit(1);
  }

  const { argv: cleanedArgv, noComments } = preprocessArgs(argv);

  const { values, positionals } = parseArgs({
    args: cleanedArgv,
    options: {
      src: { type: 'string' },
      out: { type: 'string' },
      comments: { type: 'boolean' },
      help: { type: 'boolean', short: 'h' },
      version: { type: 'boolean', short: 'v' },
    },
    allowPositionals: true,
    strict: true,
  });

  return {
    command: positionals[0] ?? null,
    src: values.src ?? 'src',
    out: values.out ?? '.',
    comments: noComments ? false : values.comments !== false,
    help: values.help === true,
    version: values.version === true,
    unknown: positionals.slice(1),
  };
}

function runInit(options) {
  const logger = createLogger();
  const cwd = process.cwd();

  logger.info('正在建立範例結構…');
  const { created, skipped } = initProject({ cwd, logger });

  if (created.length === 0) {
    logger.info('所有範例檔案都已經存在，沒有任何變更。');
  }

  logger.plain('');
  logger.title('接下來可以這樣做：');
  logger.plain(`  ${pc.cyan('npx html-block build')}    ${pc.dim('# 組裝成根目錄的 index.html')}`);
  logger.plain(`  ${pc.cyan('npx html-block watch')}    ${pc.dim('# 邊改邊看，自動重新組裝')}`);
  logger.plain('');
  logger.dim('提示：請到 src/pages/index.html 編輯內容，根目錄的 index.html 是自動產生的。');
}

function runBuild(options) {
  const logger = createLogger();
  const cwd = process.cwd();

  logger.info(`開始組裝：${options.src} → ${options.out}`);
  const result = buildProject({
    cwd,
    srcDir: options.src,
    outDir: options.out,
    comments: options.comments,
    logger,
  });

  logger.plain('');

  if (result.errors.length > 0) {
    logger.error(
      `組裝完成，但有 ${result.errors.length} 個錯誤（已產生 ${result.count} 個頁面，耗時 ${result.durationMs.toFixed(1)} ms）`,
    );
    process.exitCode = 1;
    return;
  }

  logger.success(
    `組裝完成：共 ${result.count} 個頁面，耗時 ${result.durationMs.toFixed(1)} ms`,
  );
}

async function runWatch(options) {
  const logger = createLogger();
  const cwd = process.cwd();

  const { close } = watchProject({
    cwd,
    srcDir: options.src,
    outDir: options.out,
    comments: options.comments,
    logger,
  });

  const shutdown = async () => {
    logger.plain('');
    logger.info('已停止監控，再見 👋');
    await close();
    process.exit(0);
  };

  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

async function main() {
  let options;
  try {
    options = parseCliArgs(process.argv.slice(2));
  } catch (error) {
    console.error(`${pc.red('✖')} 參數解析失敗：${error.message}`);
    console.error(HELP);
    process.exitCode = 1;
    return;
  }

  if (options.version) {
    console.log(PACKAGE.version);
    return;
  }

  if (options.help || !options.command) {
    console.log(HELP);
    return;
  }

  switch (options.command) {
    case 'init':
      runInit(options);
      break;
    case 'build':
      runBuild(options);
      break;
    case 'watch':
      await runWatch(options);
      break;
    default:
      console.error(`${pc.red('✖')} 未知指令：${options.command}`);
      console.error(HELP);
      process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(`${pc.red('✖')} 發生未預期的錯誤：${error?.stack ?? error}`);
  process.exitCode = 1;
});
