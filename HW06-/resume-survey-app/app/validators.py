"""純函式驗證層 (Pure validation functions).

本模組刻意 **不 import FastAPI / 任何框架相依套件**，只使用標準函式庫。
目的是讓商業邏輯可以被 `tests/test_unit.py` 以最快速度、最少相依地完整測試。
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

# --- 允許的設定常數 -------------------------------------------------------------

ALLOWED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp"})

MIN_EXPERIENCE = 0
MAX_EXPERIENCE = 50

# 允許：本地部分 + @ + 至少一段網域 + 至少兩碼的 TLD
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
)

DEFAULT_EXTENSION = ".bin"


# --- 驗證函式 -------------------------------------------------------------------


def validate_email(email: str) -> bool:
    """檢查 email 是否為合法格式。

    規則：必須剛好一個 ``@``、前後不可有空白、本機部位須存在、網域須含至少兩碼 TLD。
    """
    if not isinstance(email, str):
        return False

    candidate = email.strip()
    if not candidate or " " in candidate or "\t" in candidate:
        return False
    if candidate.count("@") != 1:
        return False

    return _EMAIL_RE.match(candidate) is not None


def validate_experience(years: int) -> bool:
    """檢查年資是否落在 ``0 <= years <= 50`` 的合法區間內。

    嚴格型別：只接受 ``int``（``bool`` 因為是 ``int`` 的子類別而被視為非法）。
    """
    if isinstance(years, bool) or not isinstance(years, int):
        return False

    return MIN_EXPERIENCE <= years <= MAX_EXPERIENCE


def validate_image_extension(filename: str) -> bool:
    """檢查副檔名是否為允許的圖片格式（.jpg / .jpeg / .png / .webp）。

    以「最後一個副檔名」為準，且不區分大小寫。
    ``photo.jpg.exe`` 因此會被判定為非法（真正的副檔名是 ``.exe``）。
    """
    if not isinstance(filename, str) or not filename.strip():
        return False

    suffix = Path(filename.strip()).suffix.lower()

    return suffix in ALLOWED_IMAGE_EXTENSIONS


def generate_safe_filename(original_filename: str) -> str:
    """產生安全的檔名：以 UUID4 取代原始檔名，並保留 (轉小寫的) 原副檔名。

    因為原始名稱完全被 UUID 取代，任何 ``../`` 路徑穿越片段都會自動失效。
    沒有副檔名時使用 :data:`DEFAULT_EXTENSION` 兜底。
    """
    raw = original_filename if isinstance(original_filename, str) else ""
    suffix = Path(raw.strip()).suffix.lower()

    if suffix not in ALLOWED_IMAGE_EXTENSIONS and suffix != DEFAULT_EXTENSION:
        # 保留「原副檔名」語意，但避免產生沒有副檔名或怪異副檔名的檔案。
        suffix = suffix or DEFAULT_EXTENSION

    return f"{uuid.uuid4().hex}{suffix}"
