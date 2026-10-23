"""FastAPI 進入點：路由、靜態檔案掛載。

啟動方式::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import database, validators

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# 測試隔離用：可在啟動前以環境變數覆寫預設路徑。
ENV_DB_PATH = "RESUME_DB_PATH"
ENV_UPLOAD_DIR = "RESUME_UPLOAD_DIR"

# --- 開發者測試執行器 -------------------------------------------------------------

#: 各測試套件對應的 pytest 參數（檔案路徑 / pytest-playwright 選項）。
TEST_SUITE_ARGS: dict[str, list[str]] = {
    "unit": ["tests/test_unit.py"],
    "api": ["tests/test_api.py"],
    "e2e": ["tests/test_e2e.py"],
    # 有頭慢動作：讓使用者親眼看到 Chromium 自動填表
    "e2e_headed": ["tests/test_e2e.py", "--headed", "--slowmo", "500"],
    "all": [],
}

#: 單次測試執行的最長等待時間（秒）。
TEST_RUN_TIMEOUT = 900

#: 防呆：子行程會被標記此環境變數，避免「測試再觸發測試」造成無限遞迴。
ENV_RUN_TESTS_ACTIVE = "RESUME_RUN_TESTS_ACTIVE"


class TestRunRequest(BaseModel):
    """``POST /api/run-tests`` 的請求內容。"""

    suite: Literal["unit", "api", "e2e", "e2e_headed", "all"] = "all"


def _resolve_db_path(explicit: Path | str | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get(ENV_DB_PATH, database.DEFAULT_DB_PATH))


def _resolve_upload_dir(explicit: Path | str | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get(ENV_UPLOAD_DIR, database.DEFAULT_UPLOAD_DIR))


def _as_text(value: str | bytes | None) -> str:
    """把 ``subprocess`` 可能回傳的 str / bytes / None 統一成 str。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _format_command(command: list[str]) -> str:
    """把子行程指令轉成人類可讀、可直接貼到終端機的字串。"""
    parts = []
    for token in command:
        if token == sys.executable:
            parts.append("python")
        else:
            parts.append(f'"{token}"' if " " in token else token)
    return " ".join(parts)


def create_app(
    db_path: Path | str | None = None,
    upload_dir: Path | str | None = None,
) -> FastAPI:
    """建立 FastAPI 應用程式。

    ``db_path`` / ``upload_dir`` 可顯式指定，讓測試能完全避開正式環境的
    ``data/resume.db`` 與 ``uploads/``。
    """
    resolved_db = _resolve_db_path(db_path)
    resolved_uploads = _resolve_upload_dir(upload_dir)

    resolved_uploads.mkdir(parents=True, exist_ok=True)
    database.init_db(resolved_db)

    app = FastAPI(
        title="履歷問卷蒐集系統 (Resume Survey System)",
        version="1.0.0",
        description="極簡的履歷問卷蒐集 API，附完整三層自動化測試。",
    )
    app.state.db_path = resolved_db
    app.state.upload_dir = resolved_uploads

    # --- 頁面 -----------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """履歷問卷填寫頁（含已提交卡片列表）。"""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/test-docs", include_in_schema=False)
    async def test_docs() -> FileResponse:
        """測試架構與案例說明專頁。"""
        return FileResponse(STATIC_DIR / "test-docs.html")

    # --- API ------------------------------------------------------------------

    @app.post("/api/submissions", status_code=201)
    async def create_submission(
        name: str = Form(...),
        email: str = Form(...),
        role: str = Form(...),
        experience_years: int = Form(...),
        bio: str = Form(""),
        avatar: UploadFile = File(...),
    ) -> dict[str, Any]:
        """接收 multipart/form-data，驗證後存檔並寫入資料庫。"""
        if not name.strip():
            raise HTTPException(status_code=400, detail="姓名不可為空")
        if not role.strip():
            raise HTTPException(status_code=400, detail="應徵職位不可為空")
        if not validators.validate_email(email):
            raise HTTPException(status_code=400, detail="電子郵件格式不正確")
        if not validators.validate_experience(experience_years):
            raise HTTPException(
                status_code=400,
                detail=f"年資必須介於 {validators.MIN_EXPERIENCE} 到 {validators.MAX_EXPERIENCE} 之間",
            )

        original_filename = avatar.filename or ""
        if not validators.validate_image_extension(original_filename):
            raise HTTPException(
                status_code=400,
                detail="大頭照僅允許 .jpg / .jpeg / .png / .webp 格式",
            )

        safe_filename = validators.generate_safe_filename(original_filename)
        destination = resolved_uploads / safe_filename
        destination.write_bytes(await avatar.read())

        record = database.insert_submission(
            resolved_db,
            name=name.strip(),
            email=email.strip(),
            role=role.strip(),
            experience_years=experience_years,
            bio=bio.strip(),
            avatar_path=f"uploads/{safe_filename}",
        )
        return record

    @app.get("/api/submissions")
    async def list_submissions() -> list[dict[str, Any]]:
        """取得所有已提交的履歷問卷。"""
        return database.list_submissions(resolved_db)

    @app.post("/api/run-tests")
    def run_tests(payload: TestRunRequest) -> dict[str, Any]:
        """開發者專用：執行指定測試套件並回傳完整輸出。

        ⚠️ 此端點會在專案根目錄啟動 ``python -m pytest`` 子行程，屬於**開發工具**，
        正式環境請勿對外開放。

        執行時會把 ``RESUME_DB_PATH`` / ``RESUME_UPLOAD_DIR`` 指向一次性暫存目錄，
        因此子行程（及其內部再啟動的 uvicorn）**絕不會**寫入正式的
        ``data/resume.db`` 與 ``uploads/``。

        刻意使用 ``def``（非 ``async def``），讓 FastAPI 丟到 threadpool 執行，
        測試跑得再久網頁也不會被卡住。
        """
        suite_args = TEST_SUITE_ARGS[payload.suite]
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "--tb=short",
            *suite_args,
        ]

        # 防呆：若目前行程本身就是被 /api/run-tests 啟動的子行程，就拒絕再跑一次，
        # 否則「執行全部測試」會無限遞迴（測試 → 測試 → 測試 …）。
        if os.environ.get(ENV_RUN_TESTS_ACTIVE):
            raise HTTPException(
                status_code=409,
                detail="已在測試執行中，為避免巢狀遞迴，已拒絕重複執行測試。",
            )

        started = time.perf_counter()
        stdout = ""
        stderr = ""
        returncode = 0
        timed_out = False

        with tempfile.TemporaryDirectory(prefix="resume-survey-runtests-") as sandbox:
            env = os.environ.copy()
            env[ENV_DB_PATH] = str(Path(sandbox) / "resume.db")
            env[ENV_UPLOAD_DIR] = str(Path(sandbox) / "uploads")
            env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
            env[ENV_RUN_TESTS_ACTIVE] = "1"
            env.setdefault("PYTHONIOENCODING", "utf-8")

            try:
                completed = subprocess.run(
                    command,
                    cwd=str(BASE_DIR),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=TEST_RUN_TIMEOUT,
                )
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
                returncode = completed.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stdout = _as_text(exc.stdout)
                stderr = _as_text(exc.stderr)
                stderr += (
                    f"\n[Timeout] 測試執行超過 {TEST_RUN_TIMEOUT} 秒，已中止。\n"
                )
                returncode = -1

        duration = round(time.perf_counter() - started, 2)

        return {
            "suite": payload.suite,
            "command": _format_command(command),
            "returncode": returncode,
            "passed": returncode == 0 and not timed_out,
            "timed_out": timed_out,
            "duration_seconds": duration,
            "stdout": stdout,
            "stderr": stderr,
        }

    # --- 靜態資源 --------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.mount("/uploads", StaticFiles(directory=resolved_uploads), name="uploads")

    return app


#: 正式環境使用的預設應用程式（``uvicorn app.main:app``）。
app = create_app()
