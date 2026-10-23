"""Layer 1 — Unit Test：針對 ``app/validators.py`` 純函式的完整測試。

特性：
* 不依賴 FastAPI、不依賴資料庫、不依賴網路。
* 每個函式都涵蓋 **Happy Path** 與 **Edge Case**（邊界值、錯誤型別、惡意輸入）。
"""

from __future__ import annotations

import re

import pytest

from app.validators import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_EXPERIENCE,
    MIN_EXPERIENCE,
    generate_safe_filename,
    validate_email,
    validate_experience,
    validate_image_extension,
)


# =============================================================================
# validate_email
# =============================================================================


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "first.last@example.co.uk",
        "user+tag@example.com",
        "user_name@example-domain.com",
        "USER@EXAMPLE.COM",
        "a@b.co",
    ],
)
def test_validate_email_accepts_valid_addresses(email: str) -> None:
    """Happy Path：格式正確的 Email 必須被接受。"""
    assert validate_email(email) is True


@pytest.mark.parametrize(
    "email",
    [
        "",                       # 空字串
        "   ",                    # 只有空白
        "plainstring",            # 完全沒有 @
        "no-at-sign.com",         # 網域在前面
        "user@",                  # 缺少網域
        "@example.com",           # 缺少本機部分
        "user@example",           # 缺少 TLD
        "user@example.c",         # TLD 少於 2 碼
        "user @example.com",      # 中間有空白
        "user@exam ple.com",      # 網域有空白
        "user@@example.com",      # 兩個 @
        "user@example.com.",      # 結尾多一個句點
        "user@.com",              # 空的網域標籤
        None,                     # 型別錯誤
        12345,                    # 型別錯誤
    ],
)
def test_validate_email_rejects_invalid_addresses(email) -> None:
    """Edge Case：格式錯誤的 Email 必須被拒絕，且不得拋出例外。"""
    assert validate_email(email) is False


# =============================================================================
# validate_experience
# =============================================================================


@pytest.mark.parametrize("years", [MIN_EXPERIENCE, 1, 25, 49, MAX_EXPERIENCE])
def test_validate_experience_accepts_range_boundaries(years: int) -> None:
    """邊界測試：0 與 50 為 inclusive 的合法上下界。"""
    assert validate_experience(years) is True


@pytest.mark.parametrize("years", [-1, -100, MAX_EXPERIENCE + 1, 1000, 99999])
def test_validate_experience_rejects_out_of_range_values(years: int) -> None:
    """Edge Case：負數年資或超過 50 年皆為非法。"""
    assert validate_experience(years) is False


@pytest.mark.parametrize("years", ["3", 3.5, None, True, False, [3]])
def test_validate_experience_rejects_non_integer_values(years) -> None:
    """Edge Case：型別必須嚴格為 int（bool 雖是 int 子類別仍視為非法）。"""
    assert validate_experience(years) is False


def test_validate_experience_boundaries_match_specification() -> None:
    """確認常數本身符合規格（0 ~ 50）。"""
    assert (MIN_EXPERIENCE, MAX_EXPERIENCE) == (0, 50)


# =============================================================================
# validate_image_extension
# =============================================================================


@pytest.mark.parametrize(
    "filename",
    [
        "photo.jpg",
        "photo.jpeg",
        "photo.png",
        "photo.webp",
        "PHOTO.JPG",
        "a.b.png",
        "  spaced.png  ",
    ],
)
def test_validate_image_extension_accepts_allowed_extensions(filename: str) -> None:
    """Happy Path：白名單內的副檔名（含大小寫混用、多點檔名）皆通過。"""
    assert validate_image_extension(filename) is True


@pytest.mark.parametrize(
    "filename",
    [
        "virus.exe",
        "script.sh",
        "doc.pdf",
        "archive.zip",
        "noextension",
        "photo.jpg.exe",   # 雙副檔名繞過手法
        "photo.svg",
        "",
        "   ",
        None,
        123,
    ],
)
def test_validate_image_extension_rejects_disallowed_extensions(filename) -> None:
    """Edge Case：白名單外的副檔名（含惡意 .exe）一律拒絕。"""
    assert validate_image_extension(filename) is False


def test_validate_image_extension_allowed_set() -> None:
    """確認白名單內容沒有被意外擴充。"""
    assert set(ALLOWED_IMAGE_EXTENSIONS) == {".jpg", ".jpeg", ".png", ".webp"}


# =============================================================================
# generate_safe_filename
# =============================================================================


@pytest.mark.parametrize(
    ("original", "expected_suffix"),
    [
        ("photo.png", ".png"),
        ("photo.JPG", ".jpg"),
        ("a.b.jpeg", ".jpeg"),
        ("photo.webp", ".webp"),
        ("noext", ".bin"),
    ],
)
def test_generate_safe_filename_preserves_extension(original: str, expected_suffix: str) -> None:
    """確認「保留原副檔名」：副檔名被轉小寫保留，沒有副檔名時以 .bin 兜底。"""
    safe_name = generate_safe_filename(original)

    assert safe_name.endswith(expected_suffix)
    assert re.fullmatch(r"[0-9a-f]{32}\.([a-z]+)", safe_name), safe_name


def test_generate_safe_filename_is_unique_per_call() -> None:
    """同一個檔名連續呼叫必須產生不同結果，避免覆蓋使用者檔案。"""
    first = generate_safe_filename("photo.png")
    second = generate_safe_filename("photo.png")

    assert first != second
    assert first.endswith(".png") and second.endswith(".png")


@pytest.mark.parametrize(
    "original",
    [
        "../../etc/passwd.png",
        "..\\..\\Windows\\System32\\evil.exe",
        "/etc/shadow.jpg",
    ],
)
def test_generate_safe_filename_removes_directory_components(original: str) -> None:
    """路徑穿越防護：原始檔名主體被 UUID 取代，任何目錄片段都會消失。"""
    safe_name = generate_safe_filename(original)

    assert "/" not in safe_name
    assert "\\" not in safe_name
    assert ".." not in safe_name
    assert re.fullmatch(r"[0-9a-f]{32}\.[a-z]+", safe_name), safe_name


def test_generate_safe_filename_handles_empty_input() -> None:
    """空字串或非字串輸入不得拋出例外。"""
    assert re.fullmatch(r"[0-9a-f]{32}\.bin", generate_safe_filename(""))
    assert re.fullmatch(r"[0-9a-f]{32}\.bin", generate_safe_filename(None))
