// Node.js unit tests for static/js/utils/tree.js
// Run: node --test tests/js/test_tree.mjs
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  buildTree,
  filterTree,
  collectMatchingIds,
  collectRoutes,
  normalise,
} from "../../static/js/utils/tree.js";

const sample = () => ([
  { id: 1, parent_id: null, label: "公告訊息", route: null, icon: "megaphone", sort_order: 2, required_role: "student" },
  { id: 2, parent_id: 1, label: "選課公告", route: "/page/announcement/course-selection", icon: "doc", sort_order: 1, required_role: "student" },
  { id: 3, parent_id: 1, label: "無紙化成績單公告", route: "/page/announcement/paperless-transcript", icon: "doc", sort_order: 2, required_role: "student" },
  { id: 4, parent_id: null, label: "選課與課程", route: null, icon: "book", sort_order: 3, required_role: "student" },
  { id: 5, parent_id: 4, label: "課程查詢", route: "/page/courses", icon: "search", sort_order: 1, required_role: "student" },
  { id: 6, parent_id: null, label: "系統管理", route: null, icon: "shield", sort_order: 6, required_role: "admin" },
  { id: 7, parent_id: 6, label: "選單管理", route: "/page/admin/menu", icon: "menu", sort_order: 1, required_role: "admin" },
]);

test("normalise lowercases and trims", () => {
  assert.equal(normalise("  Hello  "), "hello");
  assert.equal(normalise(null), "");
  assert.equal(normalise(123), "123");
});

test("buildTree nests children and sorts by sort_order", () => {
  const tree = buildTree(sample());
  assert.equal(tree.length, 3);
  assert.equal(tree[0].label, "公告訊息");
  assert.deepEqual(tree[0].children.map((c) => c.label), ["選課公告", "無紙化成績單公告"]);
});

test("buildTree orphans become roots", () => {
  const tree = buildTree([
    { id: 1, parent_id: 999, label: "orphan", sort_order: 0, children: [] },
  ]);
  assert.equal(tree.length, 1);
  assert.equal(tree[0].label, "orphan");
});

test("filterTree returns full tree for empty query", () => {
  const tree = buildTree(sample());
  const filtered = filterTree(tree, "");
  assert.equal(filtered.length, 3);
});

test("filterTree prunes branches without match but preserves ancestors", () => {
  const tree = buildTree(sample());
  const filtered = filterTree(tree, "選單");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].label, "系統管理");
  assert.equal(filtered[0].children[0].label, "選單管理");
});

test("filterTree returns matching leaf and its ancestors", () => {
  const tree = buildTree(sample());
  const filtered = filterTree(tree, "課程查詢");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].label, "選課與課程");
  assert.equal(filtered[0].children[0].label, "課程查詢");
});

test("filterTree is case-insensitive (matches via route)", () => {
  const tree = buildTree(sample());
  const filtered = filterTree(tree, "TRANSCRIPT");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].label, "公告訊息");
  assert.equal(filtered[0].children.length, 1);
  assert.equal(filtered[0].children[0].label, "無紙化成績單公告");
});

test("collectMatchingIds returns every node id under each match", () => {
  const ids = collectMatchingIds(sample(), "公告");
  // matches 公告訊息 (id 1), 選課公告 (id 2), 無紙化成績單公告 (id 3)
  assert.equal(ids.has(1), true);
  assert.equal(ids.has(2), true);
  assert.equal(ids.has(3), true);
  // does NOT match 課程查詢 or 選單管理
  assert.equal(ids.has(5), false);
  assert.equal(ids.has(7), false);
});

test("collectMatchingIds empty query yields empty set", () => {
  const ids = collectMatchingIds(sample(), "");
  assert.equal(ids.size, 0);
});

test("collectRoutes returns only leaf routes", () => {
  const tree = buildTree(sample());
  const routes = collectRoutes(tree);
  assert.deepEqual(routes.sort(), [
    "/page/admin/menu",
    "/page/announcement/course-selection",
    "/page/announcement/paperless-transcript",
    "/page/courses",
  ]);
});