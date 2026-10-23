"""Layer 2 — Web API Test：以 FastAPI ``TestClient`` 測試 HTTP 契約與資料持久化。

特性：
* 每個案例都使用 ``tmp_path`` 沙盒資料庫與上傳目錄，**完全不碰**正式的
  ``data/resume.db`` 與 ``uploads/``。
* 上傳的圖片使用 ``io.BytesIO`` 產生的 Mock PNG，不依賴外部檔案或網路。
"""

from __future__ import annotations

import io

import pytest

from app import database

API = "/api/submissions"
RUN_TESTS_API = "/api/run-tests"


def _skip_if_nested(response) -> None:
    """若目前測試行程本身就是 /api/run-tests 啟動的子行程，就跳過這個案例。

    這是防止「執行全部測試 → 測試再觸發測試」無限遞迴的最後一道防線；
    正常情況下（最外層執行）永遠不會進入這個分支。
    """
    if response.status_code == 409:
        pytest.skip("巢狀測試執行已被停用（此案例僅在最外層執行）")


def _files(png_bytes: bytes, filename: str = "avatar.png") -> dict:
    """建立 multipart 的檔案部分。"""
    return {"avatar": (filename, io.BytesIO(png_bytes), "image/png")}


# =============================================================================
# POST /api/submissions — Happy Path
# =============================================================================


def test_create_submission_returns_201_and_persists_record(
    client, form_payload, png_bytes
) -> None:
    """Happy Path：合法資料應回傳 201，且 JSON 內容與寫入 DB 的列一致。"""
    response = client.post(
        API,
        data=form_payload,
        files=_files(png_bytes),
    )

    assert response.status_code == 201

    body = response.json()
    assert body["id"] >= 1
    assert body["name"] == form_payload["name"]
    assert body["email"] == form_payload["email"]
    assert body["role"] == form_payload["role"]
    assert body["experience_years"] == 3
    assert body["bio"] == form_payload["bio"]
    assert body["avatar_path"].startswith("uploads/")
    assert body["avatar_path"].endswith(".png")
    assert body["created_at"]


def test_create_submission_persists_record_into_database(
    client, form_payload, png_bytes, db_path
) -> None:
    """確認 POST 真的有寫入資料庫（而不是只回應成功）。"""
    client.post(API, data=form_payload, files=_files(png_bytes))

    rows = database.list_submissions(db_path)

    assert len(rows) == 1
    assert rows[0]["name"] == form_payload["name"]
    assert rows[0]["experience_years"] == 3


def test_create_submission_saves_avatar_into_upload_dir(
    client, form_payload, png_bytes, upload_dir
) -> None:
    """確認上傳的圖片真的落地到 uploads/，且內容未被竄改。"""
    response = client.post(API, data=form_payload, files=_files(png_bytes))

    avatar_path = response.json()["avatar_path"]
    saved_file = upload_dir / avatar_path.split("/")[-1]

    assert saved_file.exists()
    assert saved_file.read_bytes() == png_bytes
    assert list(upload_dir.iterdir()) == [saved_file]


def test_create_submission_generates_unique_filenames(
    client, form_payload, png_bytes, upload_dir
) -> None:
    """兩筆同名圖片不得互相覆蓋（UUID4 檔名策略）。"""
    first = client.post(API, data=form_payload, files=_files(png_bytes)).json()
    second = client.post(API, data=form_payload, files=_files(png_bytes)).json()

    assert first["avatar_path"] != second["avatar_path"]
    assert len(list(upload_dir.iterdir())) == 2


# =============================================================================
# POST /api/submissions — 驗證失敗（400）
# =============================================================================


def test_create_submission_rejects_invalid_email(
    client, form_payload, png_bytes
) -> None:
    """非法 Email 必須被擋下並回傳 400 Bad Request。"""
    response = client.post(
        API,
        data={**form_payload, "email": "not-an-email"},
        files=_files(png_bytes),
    )

    assert response.status_code == 400
    assert "電子郵件" in response.json()["detail"]


def test_create_submission_rejects_out_of_range_experience(
    client, form_payload, png_bytes
) -> None:
    """年資負數或超過 50 都必須回傳 400，且不得寫入資料庫。"""
    for years in ("-1", "51"):
        response = client.post(
            API,
            data={**form_payload, "experience_years": years},
            files=_files(png_bytes),
        )

        assert response.status_code == 400, years
        assert "年資" in response.json()["detail"]


def test_create_submission_rejects_executable_file_extension(
    client, form_payload, png_bytes, upload_dir, db_path
) -> None:
    """惡意檔案（.exe）必須被擋下：HTTP 400、檔案不落地、資料不入庫。"""
    response = client.post(
        API,
        data=form_payload,
        files=_files(png_bytes, filename="malware.exe"),
    )

    assert response.status_code == 400
    assert "僅允許" in response.json()["detail"]
    assert list(upload_dir.iterdir()) == []
    assert database.list_submissions(db_path) == []


def test_create_submission_rejects_blank_name(client, form_payload, png_bytes) -> None:
    """只有空白的姓名必須被視為無效（伺服器端仍需防呆）。"""
    response = client.post(
        API,
        data={**form_payload, "name": "   "},
        files=_files(png_bytes),
    )

    assert response.status_code == 400
    assert "姓名" in response.json()["detail"]


def test_create_submission_rejects_blank_role(client, form_payload, png_bytes) -> None:
    """只有空白的職位同樣必須被拒絕（伺服器端仍需防呆）。"""
    response = client.post(
        API,
        data={**form_payload, "role": "   "},
        files=_files(png_bytes),
    )

    assert response.status_code == 400
    assert "職位" in response.json()["detail"]


def test_create_submission_treats_empty_string_as_missing_field(
    client, form_payload, png_bytes
) -> None:
    """完全空白的必要欄位屬於「未提供」，交由框架回傳 422（與格式錯誤的 400 區分）。"""
    response = client.post(
        API,
        data={**form_payload, "name": ""},
        files=_files(png_bytes),
    )

    assert response.status_code == 422


# =============================================================================
# POST /api/submissions — 表單層級失敗（422）
# =============================================================================


def test_create_submission_requires_avatar_file(client, form_payload) -> None:
    """缺少 avatar 欄位屬於表單必要欄位缺失，由 FastAPI 回傳 422。"""
    response = client.post(API, data=form_payload)

    assert response.status_code == 422


# =============================================================================
# GET /api/submissions
# =============================================================================


def test_list_submissions_returns_empty_list_when_no_records(client) -> None:
    """沒有資料時回傳空陣列（不是 null、也不是 404）。"""
    response = client.get(API)

    assert response.status_code == 200
    assert response.json() == []


def test_list_submissions_returns_records_ordered_by_newest_first(
    client, form_payload, png_bytes
) -> None:
    """最新提交的履歷必須排在最前面。"""
    client.post(API, data={**form_payload, "name": "甲"}, files=_files(png_bytes))
    client.post(API, data={**form_payload, "name": "乙"}, files=_files(png_bytes))

    body = client.get(API).json()

    assert [item["name"] for item in body] == ["乙", "甲"]


def test_submit_then_list_returns_the_new_record(
    client, form_payload, png_bytes
) -> None:
    """POST → GET 的完整回合：新增的履歷必須出現在列表中。"""
    client.post(API, data=form_payload, files=_files(png_bytes))

    body = client.get(API).json()

    assert len(body) == 1
    assert body[0]["name"] == form_payload["name"]
    assert body[0]["email"] == form_payload["email"]
    assert body[0]["avatar_path"].startswith("uploads/")


# =============================================================================
# 頁面路由（靜態檔案）
# =============================================================================


def test_index_page_is_served(client) -> None:
    """首頁必須回傳表單頁面。"""
    response = client.get("/")

    assert response.status_code == 200
    assert "survey-form" in response.text


def test_test_docs_page_is_served(client) -> None:
    """測試說明頁必須可以從 /test-docs 取得。"""
    response = client.get("/test-docs")

    assert response.status_code == 200
    assert "測試架構與案例說明" in response.text


# =============================================================================
# POST /api/run-tests — 開發者測試執行器
# =============================================================================


def test_run_tests_executes_unit_suite(client) -> None:
    """輕量驗證：執行 "unit" 套件應回傳 200 且 pytest 全部通過。

    這個案例刻意只跑最輕的 Unit 套件（約 1 秒），既能證明端點真的會執行
    pytest，又不會拖慢整個測試流程，也不會干擾其餘 88 個測試。
    """
    response = client.post("/api/run-tests", json={"suite": "unit"})
    _skip_if_nested(response)

    assert response.status_code == 200

    body = response.json()
    assert body["suite"] == "unit"
    assert body["returncode"] == 0
    assert body["passed"] is True
    assert body["timed_out"] is False
    assert body["duration_seconds"] >= 0
    assert "pytest" in body["command"]
    assert "tests/test_unit.py" in body["command"]
    assert "passed" in body["stdout"]


def test_run_tests_does_not_pollute_production_storage(
    client, db_path, upload_dir
) -> None:
    """執行測試後，正式的沙盒 DB 與上傳目錄不得出現任何檔案。"""
    response = client.post("/api/run-tests", json={"suite": "unit"})
    _skip_if_nested(response)

    assert list(upload_dir.iterdir()) == []
    assert database.list_submissions(db_path) == []


def test_run_tests_rejects_unknown_suite(client) -> None:
    """未知的 suite 名稱必須被擋下（Literal 型別 → 422）。"""
    response = client.post("/api/run-tests", json={"suite": "not-a-suite"})

    assert response.status_code == 422


def test_run_tests_suite_mapping_is_complete() -> None:
    """五個 suite 對應的 pytest 指令必須符合規格（純資料斷言，不實際執行）。"""
    from app.main import TEST_SUITE_ARGS

    assert set(TEST_SUITE_ARGS) == {"unit", "api", "e2e", "e2e_headed", "all"}

    assert TEST_SUITE_ARGS["unit"] == ["tests/test_unit.py"]
    assert TEST_SUITE_ARGS["api"] == ["tests/test_api.py"]
    assert TEST_SUITE_ARGS["e2e"] == ["tests/test_e2e.py"]
    assert TEST_SUITE_ARGS["e2e_headed"] == [
        "tests/test_e2e.py",
        "--headed",
        "--slowmo",
        "500",
    ]
    assert TEST_SUITE_ARGS["all"] == []


def test_run_tests_rejects_nested_execution(client, monkeypatch) -> None:
    """當行程本身是測試子行程時，必須拒絕再執行一次（避免無限遞迴）。"""
    monkeypatch.setenv("RESUME_RUN_TESTS_ACTIVE", "1")

    response = client.post("/api/run-tests", json={"suite": "unit"})

    assert response.status_code == 409
    assert "巢狀" in response.json()["detail"]
