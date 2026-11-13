/**
 * lib/logger.js
 * ---------------------------------------------------------------
 * 統一的終端機輸出格式：彩色圖示 + 繁體中文訊息。
 * 讓初學者一眼就能分辨「成功 / 注意 / 出錯」。
 */
import process from 'node:process';
import pc from 'picocolors';

/**
 * 建立一個 logger。
 * @param {{ silent?: boolean }} [options]
 */
export function createLogger(options = {}) {
  const silent = options.silent === true;

  const write = (stream, message) => {
    if (silent) return;
    stream.write(`${message}\n`);
  };

  return {
    /** 一般資訊 */
    info(message) {
      write(process.stdout, `${pc.cyan('ℹ')} ${message}`);
    },
    /** 操作成功 */
    success(message) {
      write(process.stdout, `${pc.green('✔')} ${message}`);
    },
    /** 提醒（不中斷流程） */
    warn(message) {
      write(process.stdout, `${pc.yellow('⚠')} ${message}`);
    },
    /** 錯誤（流程繼續，但最後會以非 0 exit code 結束） */
    error(message) {
      write(process.stderr, `${pc.red('✖')} ${message}`);
    },
    /** 原樣輸出（不加圖示） */
    plain(message) {
      write(process.stdout, message);
    },
    /** 淡化的輔助說明 */
    dim(message) {
      write(process.stdout, pc.dim(message));
    },
    /** 粗體標題 */
    title(message) {
      write(process.stdout, pc.bold(message));
    },
  };
}

export default createLogger;
