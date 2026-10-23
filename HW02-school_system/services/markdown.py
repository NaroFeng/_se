"""Tiny Markdown -> HTML converter for announcement content.

Supports the subset used by seed announcements:
  - `## ` / `### ` headings
  - `**bold**`, `*italic*`, `` `code` ``
  - ordered / unordered lists
  - paragraphs separated by blank lines

Intentionally avoids external dependencies to keep the demo dependency-free.
"""

import html
import re
from typing import List


_INLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"(?<!\*)\*(?!\s)([^*\n]+?)\*(?!\*)"), r"<em>\1</em>"),
]

_OL_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_UL_RE = re.compile(r"^\s*[-*]\s+(.*)$")


def _render_inline(text: str) -> str:
    out = html.escape(text, quote=False)
    for pat, repl in _INLINE_PATTERNS:
        out = pat.sub(repl, out)
    return out


def render_markdown(src: str) -> str:
    if not src:
        return ""
    lines: List[str] = src.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    paragraph: List[str] = []
    list_kind: str | None = None
    list_items: List[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{_render_inline(' '.join(paragraph).strip())}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_kind, list_items
        if list_kind and list_items:
            inner = "".join(f"<li>{_render_inline(item)}</li>" for item in list_items)
            out.append(f"<{list_kind}>{inner}</{list_kind}>")
        list_kind = None
        list_items = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush_paragraph()
            flush_list()
            continue

        if line.startswith("### "):
            flush_paragraph()
            flush_list()
            out.append(f"<h3>{_render_inline(line[4:].strip())}</h3>")
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_list()
            out.append(f"<h2>{_render_inline(line[3:].strip())}</h2>")
            continue

        m_ol = _OL_RE.match(line)
        m_ul = _UL_RE.match(line)
        if m_ol or m_ul:
            flush_paragraph()
            kind = "ol" if m_ol else "ul"
            text = m_ol.group(2) if m_ol else m_ul.group(1)
            if list_kind != kind:
                flush_list()
                list_kind = kind
            list_items.append(text)
            continue

        paragraph.append(line.strip())

    flush_paragraph()
    flush_list()
    return "\n".join(out)