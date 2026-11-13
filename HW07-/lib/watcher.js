/**
 * lib/watcher.js
 * ---------------------------------------------------------------
 * `html-block watch`：啟動一次完整 build，接著監聽 src/ 的檔案變更並自動重組。
 *
 * ⚠ 關鍵安全機制：
 *   只監聽「來源目錄（src）」，而且額外擋掉「輸出目錄內、但不在來源目錄內」的檔案。
 *   否則編譯產出的 index.html 會再次觸發 watch → 無限迴圈！
 */
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import chokidar from 'chokidar';
import { buildProject, resolveDir } from './compiler.js';
import { createLogger } from './logger.js';

/** 判斷 target 是否位於 parent 之内（含自己） */
function isInside(target, parent) {
  const rel = path.relative(parent, target);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

/**
 * 產生 chokidar 的 ignored 過濾器。
 * @returns {(target: string) => boolean}
 */
export function createIgnoreFilter(srcDir, outDir) {
  const srcRoot = path.resolve(srcDir);
  const outRoot = path.resolve(outDir);

  return (target) => {
    const resolved = path.resolve(target);
    const insideSrc = isInside(resolved, srcRoot);
    const insideOut = isInside(resolved, outRoot);

    // 輸出目錄裡、但不在來源目錄裡的東西（例如編譯產生的根目錄 index.html）→ 忽略
    if (insideOut && !insideSrc) return true;

    // .html 檔案一律監聽（即使尚未建立，也能被偵測到新增）
    if (resolved.toLowerCase().endsWith('.html')) return false;

    // 其他副檔名：如果不是目錄就忽略（目錄要放行才能繼續往下監聽）
    try {
      return !fs.statSync(resolved).isDirectory();
    } catch {
      return true;
    }
  };
}

/**
 * 啟動 watch 模式。
 * @returns {{ close: () => Promise<void> }}
 */
export function watchProject(options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const srcDir = resolveDir(options.srcDir ?? 'src', cwd);
  const outDir = resolveDir(options.outDir ?? '.', cwd);
  const comments = options.comments !== false;
  const logger = options.logger ?? createLogger();

  const runBuild = (reason) => {
    const startedAt = performance.now();
    const result = buildProject({ cwd, srcDir, outDir, comments, logger });
    const ms = (performance.now() - startedAt).toFixed(1);

    if (result.errors.length > 0) {
      logger.warn(
        `重新組裝完成，但有 ${result.errors.length} 個錯誤（${result.count} 個頁面，耗時 ${ms} ms）`,
      );
    } else {
      logger.success(`重新組裝完成：${result.count} 個頁面（耗時 ${ms} ms）`);
    }
    return { result, ms };
  };

  // ── 首次完整 build ──
  logger.info(`正在進行首次組裝：${path.relative(cwd, srcDir) || srcDir} → ${path.relative(cwd, outDir) || '.'}`);
  runBuild('init');

  const watcher = chokidar.watch(srcDir, {
    ignoreInitial: true,
    ignored: createIgnoreFilter(srcDir, outDir),
    awaitWriteFinish: { stabilityThreshold: 120, pollInterval: 30 },
  });

  let timer = null;
  let pending = null;

  const scheduleRebuild = (event, filePath) => {
    pending = { event, filePath };
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      const pendingEvent = pending;
      pending = null;
      if (!pendingEvent) return;
      const relative = path.relative(cwd, pendingEvent.filePath).split(path.sep).join('/');
      logger.info(`偵測到檔案${pendingEvent.event}：${relative}`);
      runBuild(pendingEvent.event);
    }, 80);
  };

  watcher
    .on('add', (filePath) => scheduleRebuild('新增', filePath))
    .on('change', (filePath) => scheduleRebuild('變更', filePath))
    .on('unlink', (filePath) => scheduleRebuild('刪除', filePath))
    .on('error', (error) => logger.error(`監聽發生錯誤：${error?.message ?? error}`));

  logger.info(`👀 正在監控：${path.relative(cwd, srcDir) || srcDir}（只監控 .html 檔案）`);
  logger.info(`📦 編譯輸出：${path.relative(cwd, outDir) || '.'}`);
  logger.info('已忽略輸出目錄內的 .html 檔案，避免編譯結果觸發無限迴圈。按 Ctrl+C 結束。');

  const close = async () => {
    if (timer) clearTimeout(timer);
    await watcher.close();
  };

  return { watcher, close };
}

export default watchProject;
