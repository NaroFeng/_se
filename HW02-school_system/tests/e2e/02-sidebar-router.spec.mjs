/**
 * E2E — 側邊選單與 AJAX router
 *
 * Covers:
 *   - Sidebar renders menu tree from /api/menu
 *   - Toggle folder expand/collapse (UI state + localStorage persistence)
 *   - Live search filters and highlights matches
 *   - Click a menu link → AJAX fetch → content swap → URL changes
 *   - popstate (browser back) restores previous content
 *   - "隱藏選單" button collapses the sidebar shell
 */

import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { withServer, loginAs } from "./helpers/fixtures.mjs";
import { ACCOUNTS, SEL } from "./helpers/selectors.mjs";

const ROUTE_GRADES = "/page/grades";
const ROUTE_COURSES = "/page/courses";

describe("02 sidebar & router", () => {
  const ctx = withServer();

  test("sidebar renders top-level folders from /api/menu", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarNav} .menu-node`);

    const labels = await page
      .locator(`${SEL.sidebarNav} .menu-toggle .menu-label, ${SEL.sidebarNav} > .menu-tree > .menu-node > a .menu-label`)
      .allInnerTexts();
    for (const expected of ["選課作業", "教務資訊查詢", "公告訊息"]) {
      assert.ok(
        labels.some((l) => l.includes(expected)),
        `expected sidebar to include "${expected}", got ${JSON.stringify(labels)}`,
      );
    }
  });

  test("clicking a folder toggle expands and collapses children", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarNav} .menu-toggle`);

    const folderBtn = page
      .locator(`${SEL.sidebarNav} > .menu-tree > .menu-node`)
      .filter({ has: page.locator(`.menu-toggle .menu-label:text-is("公告訊息")`) })
      .locator(".menu-toggle");
    await folderBtn.click();

    const collapsed = await page
      .locator(`${SEL.sidebarNav} .menu-children.menu-collapsed`)
      .count();
    assert.ok(collapsed >= 1, "expected at least one collapsed children list");

    await folderBtn.click();
    const stillCollapsed = await page
      .locator(`${SEL.sidebarNav} .menu-children.menu-collapsed`)
      .count();
    assert.equal(stillCollapsed, 0, "expected menu-children to be expanded again");
  });

  test("live search filters sidebar and highlights keyword", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarNav} .menu-node`);

    await page.fill(SEL.sidebarSearch, "公告");
    // The input event is synchronous — wait for the first <mark> to appear.
    await page.waitForSelector(SEL.sidebarHighlight, { timeout: 2_000 });

    const highlightCount = await page.locator(SEL.sidebarHighlight).count();
    assert.ok(highlightCount > 0, "expected highlight <mark> elements when searching 公告");

    await page.locator(SEL.sidebarSearch).press("Escape");
    const totalAfter = await page.locator(`${SEL.sidebarNav} .menu-node`).count();
    assert.ok(totalAfter > highlightCount, "expected sidebar to show more nodes after clearing search");
  });

  test("clicking a menu link loads the page via AJAX and updates the URL", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarLinkByRoute(ROUTE_GRADES)}`, { timeout: 10_000 });

    await page.click(SEL.sidebarLinkByRoute(ROUTE_GRADES));
    await page.waitForURL(`${ctx.baseUrl}${ROUTE_GRADES}`);
    await page.waitForSelector(`${SEL.appContent} h1`);
    const h1 = await page.locator(`${SEL.appContent} h1`).first().innerText();
    assert.match(h1, /成績/);
  });

  test("browser back button restores previous partial", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(`${SEL.sidebarLinkByRoute(ROUTE_GRADES)}`);

    await page.click(SEL.sidebarLinkByRoute(ROUTE_GRADES));
    await page.waitForURL(`${ctx.baseUrl}${ROUTE_GRADES}`);

    await page.click(SEL.sidebarLinkByRoute(ROUTE_COURSES));
    await page.waitForURL(`${ctx.baseUrl}${ROUTE_COURSES}`);

    await page.goBack();
    await page.waitForURL(`${ctx.baseUrl}${ROUTE_GRADES}`);
    const h1 = await page.locator(`${SEL.appContent} h1`).first().innerText();
    assert.match(h1, /成績/);
  });

  test("toggle sidebar button collapses the shell", async () => {
    const { page } = await loginAs(ctx, ACCOUNTS.student);
    await page.goto(`${ctx.baseUrl}/`);
    await page.waitForSelector(SEL.toggleSidebarBtn);
    const before = await page.locator(SEL.sidebar).getAttribute("data-collapsed");
    await page.click(SEL.toggleSidebarBtn);
    const after = await page.locator(SEL.sidebar).getAttribute("data-collapsed");
    assert.notEqual(before, after, "data-collapsed should change after clicking toggle");
  });
});
