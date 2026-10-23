/**
 * Spawn Flask server in a child process for e2e tests.
 *
 * - Uses a tmp instance DB so each run is isolated.
 * - Forces FLASK_DEBUG=0 so werkzeug does not auto-reload.
 * - Polls /api/config (public endpoint) until the server responds.
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const HOST = "127.0.0.1";
const PORT = Number(process.env.E2E_PORT || 5001);

export function getServerUrl() {
  return `http://${HOST}:${PORT}`;
}

export function getRepoRoot() {
  return REPO_ROOT;
}

/**
 * Create a tmp directory and return the DB path inside it.
 * Also returns a cleanup() callback that wipes the tmp dir.
 */
export function makeTempInstance() {
  const dir = mkdtempSync(join(tmpdir(), "nku-e2e-"));
  mkdirSync(dir, { recursive: true });
  const dbPath = join(dir, "nku_portal.sqlite");
  return {
    dbPath,
    cleanup() {
      try { rmSync(dir, { recursive: true, force: true }); } catch { /* ignore */ }
    },
  };
}

export async function startServer({ dbPath } = {}) {
  const env = {
    ...process.env,
    FLASK_DEBUG: "0",
    FLASK_RUN_PORT: String(PORT),
    SECRET_KEY: "e2e-secret",
  };
  if (dbPath) env.DATABASE_PATH = dbPath;

  // shell: true so `python` resolves via PATHEXT on Windows.
  const proc = spawn("python app.py", {
    cwd: REPO_ROOT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
    shell: true,
  });

  // Capture logs for debugging when a test fails.
  let stdout = "";
  let stderr = "";
  proc.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
  proc.stderr.on("data", (chunk) => {
    const s = chunk.toString();
    stderr += s;
    // Surface server output immediately so timeouts aren't silent.
    process.stderr.write(`[flask] ${s}`);
  });

  const base = getServerUrl();
  try {
    await waitForServer(base, proc);
  } catch (err) {
    throw new Error(
      `${err.message}\n--- Flask stdout ---\n${stdout}\n--- Flask stderr ---\n${stderr}`,
    );
  }

  return {
    proc,
    baseUrl: base,
    logs() { return { stdout, stderr }; },
    async stop() {
      if (proc.exitCode !== null) return;
      // shell:true spawns via cmd.exe on Windows; kill the whole tree.
      try { proc.kill("SIGTERM"); } catch { /* ignore */ }
      await waitForExit(proc, 5000);
      if (proc.exitCode === null) {
        try { proc.kill("SIGKILL"); } catch { /* ignore */ }
      }
    },
  };
}

async function waitForServer(baseUrl, proc) {
  const deadline = Date.now() + 30_000;
  let lastErr = null;
  while (Date.now() < deadline) {
    if (proc.exitCode !== null) {
      throw new Error(`Flask exited early (code=${proc.exitCode})`);
    }
    try {
      const res = await fetch(`${baseUrl}/api/config`);
      if (res.ok) return;
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (e) {
      lastErr = e;
    }
    await sleep(200);
  }
  throw new Error(`Flask did not become ready at ${baseUrl} within 30s (last: ${lastErr?.message})`);
}

function waitForExit(proc, timeoutMs) {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    proc.once("exit", () => { clearTimeout(timer); resolve(); });
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export const PATH_SEP = sep;
