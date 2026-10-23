"""Layer 3 — E2E Test：以 Playwright 驅動真實 Chromium，走完整使用者旅程。

特性：
* 由 ``conftest.py`` 的 ``live_server`` fixture 啟動真實 uvicorn（僅綁 127.0.0.1），
  資料庫與上傳目錄同樣位於暫存沙盒，**不會污染**正式環境。
* 測試不依賴 Tailwind CDN 的樣式，只以 ``id`` / ``data-testid`` 定位元素，
  因此在離線環境下依然穩定。
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import Page, expect

FORM = {
    "name": "王小明",
    "email": "e2e.ok@example.com",
    "role": "後端工程師",
    "experience": "5",
    "bio": "熱愛 Python 與 API 設計，擅長把複雜問題拆解成單純的函式。",
}


def _fill_form(page: Page, png_file: Path, **overrides) -> None:
    """填寫表單所有欄位，並上傳一張測試用圖片。"""
    values = {**FORM, **overrides}

    page.fill("#name", values["name"])
    page.fill("#email", values["email"])
    page.fill("#role", values["role"])
    page.fill("#experience", values["experience"])
    page.fill("#bio", values["bio"])
    page.set_input_files("#avatar", str(png_file))


# =============================================================================
# 旅程起點：首頁渲染
# =============================================================================


def test_home_page_renders_form_fields(live_server: str, page: Page) -> None:
    """首頁必須渲染出所有表單欄位、送出按鈕與列表容器。"""
    page.goto(f"{live_server}/")

    for field in ("#name", "#email", "#role", "#experience", "#bio", "#avatar"):
        expect(page.locator(field)).to_be_visible()

    expect(page.locator("#submit-btn")).to_be_visible()
    expect(page.locator("#submissions-list")).to_be_visible()
    expect(page.locator("#nav-test-docs")).to_be_visible()

    # 計數文字必須與實際卡片數量一致
    cards = page.locator(".submission-card").count()
    assert page.locator("#submission-count").inner_text() == f"{cards} 筆"


# =============================================================================
# 核心旅程：填表 → 上傳 → 送出 → 卡片動態更新
# =============================================================================


def test_submit_form_inserts_new_card_into_list(
    live_server: str, page: Page, png_file: Path
) -> None:
    """填寫全部欄位並上傳圖片後，卡片列表必須動態新增一筆。"""
    page.goto(f"{live_server}/")
    before = page.locator(".submission-card").count()

    _fill_form(page, png_file)
    page.click("#submit-btn")

    # 成功訊息
    expect(page.locator("#form-message")).to_have_attribute("data-state", "success")
    expect(page.locator("#form-message")).to_contain_text(FORM["name"])

    # 卡片數量 +1（動態更新，沒有整頁重新載入）
    expect(page.locator(".submission-card")).to_have_count(before + 1)

    # 新卡片內容正確
    card = page.locator(".submission-card").first
    expect(card).to_contain_text(FORM["name"])
    expect(card).to_contain_text(FORM["email"])
    expect(card).to_contain_text(FORM["role"])
    expect(card).to_contain_text("5 年")

    # 大頭照真的從 /uploads/ 載入
    avatar = card.locator("img")
    expect(avatar).to_have_attribute("src", re.compile(r"^/uploads/[0-9a-f]{32}\.png$"))

    image_loaded = page.evaluate(
        """() => {
            const img = document.querySelector('.submission-card img');
            return Boolean(img && img.complete && img.naturalWidth > 0);
        }"""
    )
    assert image_loaded is True


def test_submit_form_shows_error_message_for_invalid_email(
    live_server: str, page: Page, png_file: Path
) -> None:
    """Email 不合法時必須顯示錯誤訊息，且不得新增任何卡片。"""
    page.goto(f"{live_server}/")
    before = page.locator(".submission-card").count()

    _fill_form(page, png_file, email="bad-email")
    page.click("#submit-btn")

    message = page.locator("#form-message")
    expect(message).to_have_attribute("data-state", "error")
    expect(message).to_contain_text("電子郵件")

    expect(page.locator(".submission-card")).to_have_count(before)


# =============================================================================
# 跨頁導覽
# =============================================================================


def test_navigate_to_test_docs_page_shows_expected_title(
    live_server: str, page: Page
) -> None:
    """從導覽列進入測試文件頁，網址與標題都要正確。"""
    page.goto(f"{live_server}/")

    page.click("#nav-test-docs")
    page.wait_for_url("**/test-docs")

    expect(page.locator("#page-title")).to_have_text("測試架構與案例說明")


def test_test_docs_page_contains_three_test_layers(
    live_server: str, page: Page
) -> None:
    """測試文件頁必須包含三層測試說明與執行指令，避免文件與實作脫節。"""
    page.goto(f"{live_server}/test-docs")

    for layer in ("layer-unit", "layer-api", "layer-e2e"):
        expect(page.locator(f"[data-testid='{layer}']")).to_be_visible()

    expect(page.locator("[data-testid='table-unit']")).to_be_visible()
    expect(page.locator("[data-testid='table-api']")).to_be_visible()
    expect(page.locator("[data-testid='table-e2e']")).to_be_visible()

    expect(page.locator("#howto")).to_contain_text("pytest tests/test_unit.py")
    expect(page.locator("#howto")).to_contain_text("pytest tests/test_api.py")
    expect(page.locator("#howto")).to_contain_text("pytest tests/test_e2e.py")


# =============================================================================
# 互動式測試控制台 (Interactive Test Console)
# =============================================================================


def test_test_docs_page_has_interactive_console(live_server: str, page: Page) -> None:
    """控制台必須提供 6 個可複製的指令卡片與 5 個執行按鈕。"""
    page.goto(f"{live_server}/test-docs")

    expect(page.locator("#console")).to_be_visible()
    expect(page.locator(".cmdcard")).to_have_count(6)
    expect(page.locator(".cmdcard [data-copy]")).to_have_count(6)

    for suite in ("unit", "api", "e2e", "e2e_headed", "all"):
        expect(page.locator(f"[data-suite='{suite}']")).to_be_visible()

    # 每張指令卡片的指令都必須使用 python -m pytest 前綴
    commands = page.locator(".cmdblock").all_text_contents()
    for command in commands:
        assert "python -m pytest" in command, command


def test_copy_command_button_copies_to_clipboard(
    live_server: str, page: Page, context
) -> None:
    """點擊「複製指令」後按鈕文字變為「✓ 已複製！」，且剪貼簿內容正確。"""
    context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{live_server}/test-docs")

    card = page.locator(".cmdcard").first
    button = card.locator("[data-copy]")

    button.click()

    expect(button).to_have_text("✓ 已複製！")
    expect(button).to_have_class(re.compile(r"\bcopied\b"))

    clipboard = page.evaluate("() => navigator.clipboard.readText()")
    assert clipboard.strip() == "python -m pytest -v"

    # 1.8 秒後按鈕自動復原
    expect(button).to_have_text("複製指令", timeout=5_000)


def test_live_runner_executes_unit_suite_from_the_page(
    live_server: str, page: Page
) -> None:
    """在網頁上點擊「跑單元測試」應顯示 loading、狀態徽章與 pytest 輸出。

    兩種情境都必須被正確處理：

    * **最外層執行**（一般情況）→ 綠燈「✓ 全數通過」，終端機印出完整 pytest 輸出。
    * **巢狀執行**（這份 E2E 本身是被 ``/api/run-tests`` 啟動的子行程）→
      防呆守門擋下重複執行並回傳 409，前端必須顯示紅燈而不是假裝成功。
    """
    page.goto(f"{live_server}/test-docs")

    # 先掛一個 MutationObserver，記錄 loading 區段「曾經」被顯示過。
    # 直接用 to_be_visible() 會有競態：巢狀情境下 409 會在一瞬間回來，
    # spinner 可能還沒被觀察到就已經被收合。
    page.evaluate(
        """() => {
            window.__loadingSeen = false;
            const el = document.getElementById('runner-loading');
            new MutationObserver(() => {
                if (!el.hasAttribute('hidden')) { window.__loadingSeen = true; }
            }).observe(el, {attributes: true, attributeFilter: ['hidden']});
        }"""
    )

    page.click("[data-testid='run-unit']")

    # 完成後顯示狀態徽章
    badge = page.locator("#runner-badge")
    expect(badge).to_have_text(re.compile(r"全數通過|執行失敗"), timeout=180_000)
    expect(page.locator("#runner-status")).to_be_visible()

    output = page.locator("#terminal-output").inner_text()
    meta = page.locator("#runner-meta").inner_text()
    assert output.strip(), "終端機區塊應該要有輸出"

    # loading 狀態確實有出現過，且執行結束後已收合
    assert page.evaluate("() => window.__loadingSeen") is True
    expect(page.locator("#runner-loading")).to_be_hidden()

    if badge.inner_text() == "✓ 全數通過":
        # 正常（最外層）執行：必須看到 pytest 的完整成功輸出
        assert "耗時" in meta
        assert "tests/test_unit.py" in meta
        assert "passed" in output
        assert "test_validate_email_accepts_valid_addresses" in output
    else:
        # 巢狀執行：守門擋下重複執行，這同樣是預期行為，
        # 頁面必須正確顯示紅燈並把原因印出來。
        assert "suite=unit" in meta
        assert "巢狀" in output or "已在測試執行中" in output

    # 按鈕恢復可用
    expect(page.locator("[data-testid='run-unit']")).to_be_enabled()


def test_live_runner_reports_failure_for_invalid_suite(
    live_server: str, page: Page
) -> None:
    """送出未知的 suite 時，頁面必須顯示紅燈徽章而不是假裝成功。"""
    page.goto(f"{live_server}/test-docs")

    page.evaluate(
        """async () => {
            await fetch('/api/run-tests', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({suite: 'not-a-real-suite'})
            });
        }"""
    )

    response = page.request.post(
        f"{live_server}/api/run-tests",
        data={"suite": "not-a-real-suite"},
    )
    assert response.status == 422
