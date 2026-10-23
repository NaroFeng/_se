"""Pytest 共用 fixtures：負責環境隔離、測試資料庫、Mock 圖片與 E2E 測試伺服器。

設計原則（對應 test-docs.html 的「測試隔離說明」）：

* **sys.path**：把專案根目錄加入 ``sys.path``，讓 ``import app.validators`` 可用。
* **環境隔離**：在 ``import app.main`` *之前* 設定 ``RESUME_DB_PATH`` / ``RESUME_UPLOAD_DIR``，
  避免模組層級的 ``app = create_app()`` 碰到正式環境的 ``data/resume.db`` 與 ``uploads/``。
* **沙盒資料庫**：每個 API 測試案例都拿到 ``tmp_path`` 底下的全新資料庫與上傳目錄。
* **E2E 伺服器**：以子行程啟動真實 uvicorn，資料庫與上傳目錄同樣指向暫存沙盒。
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Iterator

import pytest

# --- sys.path：讓 `app` 套件可被匯入 ------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- 環境隔離：必須在 import app.main 之前完成 ------------------------------------

_SANDBOX_ROOT = Path(tempfile.mkdtemp(prefix="resume-survey-sandbox-"))
os.environ.setdefault("RESUME_DB_PATH", str(_SANDBOX_ROOT / "resume.db"))
os.environ.setdefault("RESUME_UPLOAD_DIR", str(_SANDBOX_ROOT / "uploads"))


def _cleanup_sandbox() -> None:
    shutil.rmtree(_SANDBOX_ROOT, ignore_errors=True)


atexit.register(_cleanup_sandbox)

from app.main import create_app  # noqa: E402  (必須在環境變數設定之後才匯入)


# --- Mock 圖片工具 ----------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def make_png_bytes(width: int = 1, height: int = 1, color: tuple[int, int, int] = (37, 99, 235)) -> bytes:
    """產生一張合法的 PNG 位元組（不需要 Pillow，也不需要二進位素材檔）。"""
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    idat = zlib.compress(raw)
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


@pytest.fixture()
def png_bytes() -> bytes:
    """一張合法的 1x1 PNG 圖片內容。"""
    return make_png_bytes()


@pytest.fixture()
def png_file(tmp_path: Path) -> Path:
    """把合法 PNG 寫到暫存目錄，供 Playwright 的 set_input_files 使用。"""
    path = tmp_path / "avatar.png"
    path.write_bytes(make_png_bytes(8, 8))
    return path


# --- API 測試用 fixtures -----------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    """沙盒用的 SQLite 檔案路徑（每個案例獨立）。"""
    return tmp_path / "data" / "resume.db"


@pytest.fixture()
def upload_dir(tmp_path: Path) -> Path:
    """沙盒用的圖片上傳目錄（每個案例獨立）。"""
    return tmp_path / "uploads"


@pytest.fixture()
def app(db_path: Path, upload_dir: Path):
    """指向沙盒資料庫的 FastAPI 應用程式。"""
    return create_app(db_path=db_path, upload_dir=upload_dir)


@pytest.fixture()
def client(app):
    """FastAPI TestClient（ASGI in-process，不佔用真實 TCP 埠）。"""
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def form_payload() -> dict:
    """一份合法的 multipart 表單欄位（不含檔案部分）。"""
    return {
        "name": "王小明",
        "email": "ming@example.com",
        "role": "後端工程師",
        "experience_years": "3",
        "bio": "熱愛 Python 與 API 設計。",
    }


# --- E2E 測試用 fixtures -----------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """啟動真實的 uvicorn 伺服器（僅綁定 127.0.0.1），回傳 base URL。"""
    workdir = tmp_path_factory.mktemp("live-server")
    server_db = workdir / "data" / "resume.db"
    server_uploads = workdir / "uploads"

    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["RESUME_DB_PATH"] = str(server_db)
    env["RESUME_UPLOAD_DIR"] = str(server_uploads)
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    )
    env.setdefault("PYTHONIOENCODING", "utf-8")

    stdout_path = workdir / "uvicorn.out.log"
    stderr_path = workdir / "uvicorn.err.log"

    with open(stdout_path, "wb") as stdout_file, open(stderr_path, "wb") as stderr_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
        )

        deadline = time.time() + 60
        ready = False
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"{base_url}/api/submissions", timeout=1
                ) as response:
                    if response.status == 200:
                        ready = True
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.25)

        if not ready:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            raise RuntimeError(
                "E2E 測試伺服器啟動失敗：\n"
                f"{stdout_path.read_text(encoding='utf-8', errors='replace')}\n"
                f"{stderr_path.read_text(encoding='utf-8', errors='replace')}"
            )

        try:
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
