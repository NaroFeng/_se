// Node.js unit tests for static/js/utils/highlight.js
import { test } from "node:test";
import assert from "node:assert/strict";

import { highlightSegments, highlightToHtml } from "../../static/js/utils/highlight.js";

test("highlightSegments returns single segment for empty query", () => {
  const segs = highlightSegments("hello world", "");
  assert.deepEqual(segs, [{ text: "hello world", match: false }]);
});

test("highlightSegments splits around a single match", () => {
  const segs = highlightSegments("選課公告列表", "公告");
  assert.deepEqual(segs, [
    { text: "選課", match: false },
    { text: "公告", match: true },
    { text: "列表", match: false },
  ]);
});

test("highlightSegments is case-insensitive", () => {
  const segs = highlightSegments("Hello WORLD", "world");
  assert.deepEqual(segs, [
    { text: "Hello ", match: false },
    { text: "WORLD", match: true },
  ]);
});

test("highlightSegments finds multiple matches", () => {
  const segs = highlightSegments("公告 公告 公告", "公告");
  assert.equal(segs.filter((s) => s.match).length, 3);
});

test("highlightToHtml escapes special characters", () => {
  const html = highlightToHtml("<script>alert(1)</script>", "alert");
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.ok(html.includes("<mark>alert</mark>"));
});

test("highlightToHtml renders no mark when query is empty", () => {
  const html = highlightToHtml("plain text", "");
  assert.equal(html, "plain text");
  assert.ok(!html.includes("<mark>"));
});

test("highlightToHtml handles null / undefined safely", () => {
  assert.equal(highlightToHtml(null, "x"), "");
  assert.equal(highlightToHtml(undefined, ""), "");
});