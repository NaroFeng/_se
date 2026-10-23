"""Markdown rendering tests."""
from services.markdown import render_markdown


def test_renders_headings():
    html = render_markdown("## Title\n\ntext")
    assert "<h2>Title</h2>" in html
    assert "<p>text</p>" in html


def test_renders_three_level_headings():
    html = render_markdown("### sub")
    assert "<h3>sub</h3>" in html


def test_renders_ordered_list():
    html = render_markdown("1. one\n2. two\n3. three")
    assert html.startswith("<ol>") or "<ol>" in html
    assert "<li>one</li>" in html
    assert "<li>three</li>" in html


def test_renders_unordered_list():
    html = render_markdown("- a\n- b")
    assert "<ul>" in html
    assert "<li>a</li>" in html


def test_renders_inline_formatting():
    html = render_markdown("**bold** and *em* and `code`")
    assert "<strong>bold</strong>" in html
    assert "<em>em</em>" in html
    assert "<code>code</code>" in html


def test_escapes_html_special_chars():
    html = render_markdown("a < b > c")
    assert "&lt;" in html
    assert "&gt;" in html
    assert "<b>" not in html


def test_empty_input_returns_empty_string():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""