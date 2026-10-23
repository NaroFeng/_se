/**
 * E2E — 登入與首頁
 *
 * Covers:
 *   - Anonymous -> / bounces to /login
 *   - Form fallback login (POST /login) with wrong creds shows error
 *   - Form fallback login with correct creds redirects to /
 *   - JS-driven login (login.js) lands on home with sidebar visible
 *   - Sidebar shows role-appropriate items
 *   - Logout returns to /login
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { withServer, loginAs, newPage } from "./helpers/fixtures.mjs";
import { ACCOUNTS, SEL } from "./helpers/selectors.mjs";

describe("01 login & home", () => {
  const ctx = withServer();

  test("anonymous visit to / redirects to /login", async () => {
    const { page } = await newPage(ctx);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForURL(/\/login$/);
    assert.match(page.url(), /\/login$/);
    assert.equal(await page.locator(SEL.loginForm).count(), 1);
  });

  test("form login with wrong password shows error", async () => {
    const { page } = await newPage(ctx);
    await page.goto(`${ctx.baseUrl}/login`);
    await page.fill(SEL.loginUsername, ACCOUNTS.student.username);
    await page.fill(SEL.loginPassword, "wrong-password");
    await page.click(SEL.loginSubmit);
    await page.waitForSelector(`${SEL.loginError}:not([hidden])`);
    const txt = await page.locator(SEL.loginError).innerText();
    assert.match(txt, /帳號或密碼|錯誤|失敗/);
  });

  test("form login with correct password lands on home", async () => {
    const { page } = await newPage(ctx);
    await page.goto(`${ctx.baseUrl}/login`);
    await page.fill(SEL.loginUsername, ACCOUNTS.student.username);
    await page.fill(SEL.loginPassword, ACCOUNTS.student.password);
    await page.click(SEL.loginSubmit);
    await page.waitForURL(`${ctx.baseUrl}/`);
    await page.waitForSelector(SEL.sidebar);
    await page.waitForSelector(SEL.appContent);
    const userInfo = await page.locator(".user-info").innerText();
    assert.match(userInfo, /馮至豪/);
  });

  test("API login then visit / shows sidebar with role-appropriate items", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarNav} .menu-node`);
    // "系統管理" is a folder (no route). Use sidebarItemByLabel to match
    // either a link or a folder toggle.
    const sysAdminItem = page.locator(SEL.sidebarItemByLabel("系統管理"));
    assert.equal(await sysAdminItem.count(), 1, "admin should see 系統管理 folder");
  });

  test("student role hides admin-only menu items", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarNav} .menu-node`);
    const sysAdminItem = page.locator(SEL.sidebarItemByLabel("系統管理"));
    assert.equal(await sysAdminItem.count(), 0, "student should not see 系統管理 folder");
  });

  test("logout returns user to /login", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(SEL.logoutForm);
    await page.click(SEL.logoutBtn);
    await page.waitForURL(/\/login$/);
    const me = await page.request.get(`${ctx.baseUrl}/api/auth/me`);
    assert.equal(me.status(), 401);
  });

  test("login page has the demo account hint", async () => {
    const { page } = await newPage(ctx);
    await page.goto(`${ctx.baseUrl}/login`);
    const hint = await page.locator(".login-hint").innerText();
    assert.match(hint, /s114210501|pass1234/);
  });
});
