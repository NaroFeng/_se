/**
 * E2E — 人員管理 (admin)
 *
 * Covers:
 *   - Admin lands on /page/admin/users with table populated
 *   - Search box filters the table (debounced)
 *   - Role / status filters narrow the list
 *   - "＋ 新增人員" opens drawer; saving creates a row
 *   - "編輯" opens drawer with prefilled values; saving updates the row
 *   - "重設密碼" modal: setting a new password works
 *   - "刪除" with confirm() removes the row
 *   - "下載模板" hits the template.csv endpoint
 *   - "批次匯入" uploads a small CSV and shows the result modal
 *
 * Native dialogs: delete uses confirm(), import-result modal uses native
 * <dialog>. We register page.on("dialog") to auto-accept.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { withServer, loginAs, newPage } from "./helpers/fixtures.mjs";
import { ACCOUNTS, SEL } from "./helpers/selectors.mjs";

describe("04 users admin", () => {
  const ctx = withServer();

  test("admin sees users table with seeded accounts", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(`${SEL.usersTbody} tr`);
    const summary = await page.locator(SEL.usersSummary).innerText();
    assert.match(summary, /共 \d+ 筆/);
    const adminRow = page.locator(SEL.usersRowByUsername("admin"));
    assert.equal(await adminRow.count(), 1, "expected admin row");
  });

  test("search filters table by username", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(`${SEL.usersTbody} tr`);

    await page.fill(SEL.usersSearch, "teacher01");
    await page.waitForFunction(
      () => /teacher01/.test(document.querySelector("#users-tbody")?.textContent || ""),
      null,
      { timeout: 3_000 },
    );
    const visibleRows = await page.locator(`${SEL.usersTbody} tr`).count();
    assert.ok(visibleRows >= 1);
  });

  test("role filter shows only students", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(`${SEL.usersTbody} tr`);

    await page.selectOption(SEL.usersFilterRole, "student");
    await page.waitForFunction(
      () => {
        const rows = document.querySelectorAll("#users-tbody tr .badge-role-student");
        const dataRows = document.querySelectorAll("#users-tbody tr[data-id]");
        return dataRows.length > 0 && rows.length === dataRows.length;
      },
      null,
      { timeout: 3_000 },
    );
  });

  test("admin can create a new student via the drawer", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(SEL.usersNew);

    await page.click(SEL.usersNew);
    await page.waitForSelector(`${SEL.usersDrawer}.drawer-open`);

    const username = `e2e_${Date.now()}`;
    await page.fill("input[name='username']", username);
    await page.fill("input[name='display_name']", "E2E Student");
    await page.fill("input[name='password']", "pass1234");
    await page.selectOption("select[name='role']", "student");
    await page.fill("input[name='student_id']", username);
    await page.fill("input[name='year_enrolled']", "115");
    await page.click(SEL.usersFormSubmit);

    await page.waitForSelector(SEL.usersRowByUsername(username), { timeout: 5_000 });
  });

  test("admin can edit a user's display name", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(`${SEL.usersTbody} tr`);

    const row = page.locator(`${SEL.usersTbody} tr:has(code:text-is("teacher01"))`);
    await row.locator("button[data-action='edit']").click();
    await page.waitForSelector(`${SEL.usersDrawer}.drawer-open`);

    const newName = `王小明E2E-${Date.now()}`;
    await page.fill("input[name='display_name']", newName);
    await page.click(SEL.usersFormSubmit);

    await page.waitForFunction(
      (n) => Array.from(document.querySelectorAll("#users-tbody tr")).some(
        (tr) => tr.textContent && tr.textContent.includes(n),
      ),
      newName,
      { timeout: 5_000 },
    );
  });

  test("admin can reset a user's password", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(`${SEL.usersTbody} tr`);

    const row = page.locator(`${SEL.usersTbody} tr:has(code:text-is("teacher01"))`);
    await row.locator("button[data-action='reset-pw']").click();
    await page.waitForSelector(`${SEL.resetPwModal}[open]`);
    await page.fill(`${SEL.resetPwModal} input[name='new_password']`, "newpw9999");
    await page.click(SEL.resetPwSubmit);
    await page.waitForFunction(
      () => !document.querySelector("#reset-pw-modal")?.hasAttribute("open"),
      null,
      { timeout: 5_000 },
    );

    const res = await page.request.post(`${ctx.baseUrl}/api/auth/login`, {
      data: { username: "teacher01", password: "newpw9999" },
    });
    assert.ok(res.ok(), `expected login with new password to succeed (status=${res.status()})`);
  });

  test("admin can delete a non-essential account", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    page.on("dialog", (d) => d.accept());

    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(SEL.usersNew);

    const username = `e2e_del_${Date.now()}`;
    await page.click(SEL.usersNew);
    await page.waitForSelector(`${SEL.usersDrawer}.drawer-open`);
    await page.fill("input[name='username']", username);
    await page.fill("input[name='display_name']", "To Delete");
    await page.fill("input[name='password']", "pass1234");
    await page.click(SEL.usersFormSubmit);
    await page.waitForSelector(SEL.usersRowByUsername(username));

    const row = page.locator(SEL.usersRowByUsername(username));
    await row.locator("button[data-action='delete']").click();
    await page.waitForFunction(
      (u) => !document.querySelector(`#users-tbody tr:has(code:text-is("${u}"))`),
      username,
      { timeout: 5_000 },
    );
    assert.equal(await page.locator(SEL.usersRowByUsername(username)).count(), 0);
  });

  test("admin can download the CSV template", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(SEL.usersDownloadTemplate);

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click(SEL.usersDownloadTemplate),
    ]);
    assert.match(download.suggestedFilename(), /template.*\.csv$/i);
  });

  test("admin can bulk import a CSV", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/users`);
    await page.waitForSelector(SEL.usersImportFile);

    const csv = [
      "username,password,display_name,department_code,role,student_id,email",
      `e2e_imp_${Date.now()},pass1234,E2E Imported,CS,student,e2e_imp,imp@nku.edu.tw`,
    ].join("\n");

    await page.setInputFiles(SEL.usersImportFile, {
      name: "import.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("\uFEFF" + csv, "utf-8"),
    });

    await page.waitForSelector("#import-result-modal[open]", { timeout: 5_000 });
    const summary = await page.locator("#import-result-summary").innerText();
    assert.match(summary, /建立 1/);
  });

  test("non-admin gets 403 when calling admin user APIs directly", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    const res = await page.request.get(`${ctx.baseUrl}/api/admin/users`);
    assert.equal(res.status(), 403, `expected 403, got ${res.status()}`);
  });
});
