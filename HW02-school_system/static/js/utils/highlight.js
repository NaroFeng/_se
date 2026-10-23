/**
 * Pure text-highlighting helper.
 * Splits text into an array of {text, match} segments so a renderer can
 * wrap matches in <mark> without touching the DOM here.
 */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/**
 * Highlight occurrences of `query` (case-insensitive) inside `text`.
 * Returns an array of segments safe to render as HTML.
 */
export function highlightSegments(text, query) {
  const src = String(text == null ? "" : text);
  const q = (query == null ? "" : String(query)).trim();
  if (!q) return [{ text: src, match: false }];

  const lowerSrc = src.toLowerCase();
  const lowerQ = q.toLowerCase();
  const out = [];
  let cursor = 0;
  while (cursor < src.length) {
    const idx = lowerSrc.indexOf(lowerQ, cursor);
    if (idx === -1) {
      out.push({ text: src.slice(cursor), match: false });
      break;
    }
    if (idx > cursor) out.push({ text: src.slice(cursor, idx), match: false });
    out.push({ text: src.slice(idx, idx + q.length), match: true });
    cursor = idx + q.length;
  }
  return out;
}

/**
 * Render the segments into an HTML string with <mark> tags around matches.
 * HTML-special chars are escaped.
 */
export function highlightToHtml(text, query) {
  return highlightSegments(text, query)
    .map((seg) => (seg.match ? `<mark>${escapeHtml(seg.text)}</mark>` : escapeHtml(seg.text)))
    .join("");
}

export const __test__ = { escapeHtml };