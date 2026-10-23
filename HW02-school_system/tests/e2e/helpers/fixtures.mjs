/**
 * Reusable test fixtures.
 *
 * Lifecycle:
 *   - One Flask server + one tmp DB per test file (faster, isolated enough
 *     for the scenarios we cover).
 *   - One Chromium browser per test file; fresh context per test for session
 *     isolation.
 *
 * Usage in a spec file:
 *
 *   import { withServer, loginAs, loginViaForm, newPage } from "./helpers/fixtures.mjs";
 *   import { ACCOUNTS } from "./helpers/selectors.mjs";
 *
 *   describe("...", () => {
 *     const ctx = withServer();
 *     test("...", async () => { ... use ctx.browser, ctx.baseUrl ... });
 *   });
 *
 * Note: node:test exports `before`/`after` at module top-level. They register
 * hooks for the enclosing test file. We call them inside `withServer()` so the
 * caller stays declarative.
 */

import { before, after, test } from "node:test";
import { chromium } from "playwright";
import { startServer, getServerUrl, makeTempInstance } from "./server.mjs";

/**
 * Register Flask-server + browser lifecycle hooks and return a `ctx` object
 * that tests can read from. Returns synchronously; resources are ready by the
 * time tests actually run because `before` blocks the file.
 */
export function withServer() {
  const ctx = {
    server: null,
    tmp: null,
    baseUrl: null,
    browser: null,
  };

  before(async () => {
    ctx.tmp = makeTempInstance();
    ctx.server = await startServer({ dbPath: ctx.tmp.dbPath });
    ctx.baseUrl = ctx.server.baseUrl;
    // Set HEADED=1 to watch the browser, SLOWMO=<ms> to slow each action down.
    ctx.browser = await chromium.launch({
      headless: process.env.HEADED !== "1",
      slowMo: Number(process.env.SLOWMO || 0),
    });
    // Single shared context → only one window opens in headed mode.
    // Tests still get session isolation because we clear cookies/storage
    // and reuse the same page via newPage() — see below.
    ctx.context = await ctx.browser.newContext();
  });

  after(async () => {
    if (ctx.context) await ctx.context.close();
    if (ctx.browser) await ctx.browser.close();
    if (ctx.server) await ctx.server.stop();
    if (ctx.tmp) ctx.tmp.cleanup();
  });

  return ctx;
}

/**
 * Get a page on the shared context. Cookies, localStorage, and session
 * storage are cleared so each test starts from a known state, but the
 * browser window is reused (no second window pops up in headed mode).
 */
export async function newPage(ctx) {
  await ctx.context.clearCookies();
  const page = ctx.page ?? await ctx.context.newPage();
  ctx.page = page;
  // Only run storage clears after the page has navigated somewhere; calling
  // evaluate() on about:blank adds latency and the clears silently no-op.
  if (!page.url().startsWith("about:")) {
    await page.evaluate(() => {
      try { localStorage.clear(); } catch {}
      try { sessionStorage.clear(); } catch {}
    });
  }
  return { page, context: ctx.context };
}

/** Login via API (faster than UI) then return the shared context. */
export async function loginAs(ctx, account) {
  const { page, context } = await newPage(ctx);
  const res = await context.request.post(`${ctx.baseUrl}/api/auth/login`, {
    data: { username: account.username, password: account.password },
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok()) {
    const body = await res.text();
    throw new Error(`Login failed for ${account.username}: ${res.status()} ${body}`);
  }
  return { page, context };
}

/** Login via the UI (the form path — used to test form fallback). */
export async function loginViaForm(page, baseUrl, account) {
  await page.goto(`${baseUrl}/login`);
  await page.fill("input[name='username']", account.username);
  await page.fill("input[name='password']", account.password);
  await page.click("#login-form button[type='submit']");
  await page.waitForURL(`${baseUrl}/`);
}

export { test, getServerUrl };
