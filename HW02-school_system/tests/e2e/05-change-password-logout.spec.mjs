/**
 * E2E — 修改密碼 & 登出
 *
 * Covers:
 *   - Header "修改密碼" button opens the dialog
 *   - Wrong old password → error shown, dialog stays open
 *   - Mismatched new/confirm → client-side error shown
 *   - Valid submission closes dialog (via .close("confirm"))
 *   - After change, re-login with new password works; old password rejected
 *   - Header logout button ends session (back to /login)
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { withServer, loginAs } from "./helpers/fixtures.mjs";
import { ACCOUNTS, SEL } from "./helpers/selectors.mjs";

describe("05 change password & logout", () => {
  const ctx = withServer();

  test("change password modal opens from header button", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(SEL.changePasswordBtn);
    await page.click(SEL.changePasswordBtn);
    await page.waitForSelector(`${SEL.changePasswordModal}[open]`);
    assert.equal(await page.locator(SEL.changePasswordModal).count(), 1);
  });

  test("wrong old password shows error and keeps dialog open", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.click(SEL.changePasswordBtn);
    await page.waitForSelector(`${SEL.changePasswordModal}[open]`);

    await page.fill(SEL.changePasswordOld, "wrong-old");
    await page.fill(SEL.changePasswordNew, "newpass9999");
    await page.fill(SEL.changePasswordConfirm, "newpass9999");
    await page.click(SEL.changePasswordSubmit);

    await page.waitForSelector(`${SEL.changePasswordError}:not([hidden])`, { timeout: 5_000 });
    const errText = await page.locator(SEL.changePasswordError).innerText();
    assert.match(errText, /密碼|錯誤|fail/);
    assert.equal(await page.locator(`${SEL.changePasswordModal}[open]`).count(), 1);
  });

  test("mismatched new/confirm passwords shows client error", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.click(SEL.changePasswordBtn);
    await page.waitForSelector(`${SEL.changePasswordModal}[open]`);

    await page.fill(SEL.changePasswordOld, ACCOUNTS.student.password);
    await page.fill(SEL.changePasswordNew, "newpass1111");
    await page.fill(SEL.changePasswordConfirm, "newpass2222");
    await page.click(SEL.changePasswordSubmit);

    await page.waitForSelector(`${SEL.changePasswordError}:not([hidden])`);
    const errText = await page.locator(SEL.changePasswordError).innerText();
    assert.match(errText, /不一致|密碼/);
  });

  test("valid change closes dialog; new password works on re-login", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.click(SEL.changePasswordBtn);
    await page.waitForSelector(`${SEL.changePasswordModal}[open]`);

    await page.fill(SEL.changePasswordOld, ACCOUNTS.student.password);
    await page.fill(SEL.changePasswordNew, "newpw_e2e_42");
    await page.fill(SEL.changePasswordConfirm, "newpw_e2e_42");
    await page.click(SEL.changePasswordSubmit);

    await page.waitForFunction(
      () => !document.querySelector("#change-password-modal")?.hasAttribute("open"),
      null,
      { timeout: 5_000 },
    );

    await page.click(SEL.logoutBtn);
    await page.waitForURL(/\/login$/);

    const oldRes = await page.request.post(`${ctx.baseUrl}/api/auth/login`, {
      data: { username: ACCOUNTS.student.username, password: ACCOUNTS.student.password },
    });
    assert.equal(oldRes.status(), 401, "old password should be rejected");

    const newRes = await page.request.post(`${ctx.baseUrl}/api/auth/login`, {
      data: { username: ACCOUNTS.student.username, password: "newpw_e2e_42" },
    });
    assert.ok(newRes.ok(), `new password should work (status=${newRes.status()})`);
  });

  test("logout button clears session and bounces to /login", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.teacher);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(SEL.logoutBtn);
    await page.click(SEL.logoutBtn);
    await page.waitForURL(/\/login$/);

    const res = await page.request.get(`${ctx.baseUrl}/api/menu`);
    assert.equal(res.status(), 401);
  });
});
