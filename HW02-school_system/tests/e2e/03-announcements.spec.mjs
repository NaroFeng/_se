/**
 * E2E — 公告 CRUD
 *
 * Covers:
 *   - Student: open announcement list → click into detail → see markdown body
 *   - Admin: navigate to /page/admin/announcements
 *   - Admin: create a new announcement via the form (slug, title, content)
 *   - Admin: edit existing announcement, see it persist on the list
 *   - Admin: delete announcement via the form's delete button
 *   - Student can see the newly-created announcement in the list & detail
 *
 * Note: delete uses a native `confirm()` dialog. We register a Playwright
 * dialog handler that auto-accepts.
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { withServer, loginAs } from "./helpers/fixtures.mjs";
import { ACCOUNTS, SEL } from "./helpers/selectors.mjs";

describe("03 announcements", () => {
  const ctx = withServer();

  test("student can browse announcement list and open a detail", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/page/announcements`);
    await page.waitForSelector(`${SEL.appContent} h1`);

    const link = page.locator("a[data-route='/page/announcement/course-selection']");
    assert.ok(await link.count() >= 1, "expected course-selection link in list");
    await link.first().click();
    await page.waitForURL(/\/page\/announcement\/course-selection$/);
    await page.waitForSelector(`${SEL.appContent} h1`);
    const h1 = await page.locator(`${SEL.appContent} h1`).innerText();
    assert.match(h1, /選課/);
    const body = await page.locator(`${SEL.appContent} .doc-body`).innerText();
    assert.match(body, /選課/);
  });

  test("admin can create a new announcement", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/announcements`);
    await page.waitForSelector(SEL.adminAnnForm);

    await page.click(SEL.adminAnnNewBtn);
    const slug = `e2e-${Date.now()}`;
    await page.fill("input[name='slug']", slug);
    await page.fill("input[name='title']", "E2E 測試公告");
    await page.fill("input[name='category']", "測試");
    await page.fill("input[name='author']", "E2E Bot");
    await page.fill("textarea[name='content']", "## Hello\n\nThis is **bold**.");
    await page.click(SEL.adminAnnSaveBtn);

    await page.waitForSelector(SEL.adminAnnItemBySlug(slug), { timeout: 5_000 });
    assert.ok(await page.locator(SEL.adminAnnItemBySlug(slug)).count() >= 1);
  });

  test("admin can edit an existing announcement", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    await page.goto(`${ctx.baseUrl}/page/admin/announcements`);
    await page.waitForSelector(`${SEL.adminAnnList} button[data-slug]`);

    const first = page.locator(`${SEL.adminAnnList} button[data-slug]`).first();
    const slug = await first.getAttribute("data-slug");
    await first.click();
    await page.waitForFunction(
      (s) => document.querySelector("#admin-ann-form input[name='slug']")?.value === s,
      slug,
    );
    const newTitle = `Edited ${Date.now()}`;
    await page.fill("input[name='title']", newTitle);
    await page.click(SEL.adminAnnSaveBtn);

    await page.waitForFunction(
      (t) => Array.from(document.querySelectorAll("#admin-ann-list strong")).some((el) => el.textContent === t),
      newTitle,
      { timeout: 5_000 },
    );
  });

  test("admin can delete an announcement (after creating one)", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.admin);
    page.on("dialog", (d) => d.accept());

    await page.goto(`${ctx.baseUrl}/page/admin/announcements`);
    await page.waitForSelector(SEL.adminAnnForm);

    await page.click(SEL.adminAnnNewBtn);
    const slug = `e2e-del-${Date.now()}`;
    await page.fill("input[name='slug']", slug);
    await page.fill("input[name='title']", "to-delete");
    await page.fill("textarea[name='content']", "to delete");
    await page.click(SEL.adminAnnSaveBtn);
    await page.waitForSelector(SEL.adminAnnItemBySlug(slug));

    await page.click(SEL.adminAnnItemBySlug(slug));
    await page.click(SEL.adminAnnDeleteBtn);
    await page.waitForFunction(
      (s) => !document.querySelector(`#admin-ann-list button[data-slug='${s}']`),
      slug,
      { timeout: 5_000 },
    );
    assert.equal(await page.locator(SEL.adminAnnItemBySlug(slug)).count(), 0);
  });

  test("student sees a newly-created announcement in the list", async () => {
    const slug = `e2e-visible-${Date.now()}`;

    {
      const { context } = await loginAs(ctx, ACCOUNTS.admin);
      const res = await context.request.post(`${ctx.baseUrl}/api/admin/announcements`, {
        data: {
          slug,
          title: "Student-visible E2E",
          category: "測試",
          author: "E2E",
          content: "## Title\n\nbody",
        },
      });
      assert.ok(res.ok(), `expected 2xx got ${res.status()}`);
    }

    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/page/announcements`);
    await page.waitForSelector(`${SEL.appContent} h1`);
    const link = page.locator(`a[data-route='/page/announcement/${slug}']`);
    assert.equal(await link.count(), 1, "student should see the new announcement link");
  });
});
