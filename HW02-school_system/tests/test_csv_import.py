"""CSV bulk import / export round-trip tests."""
import io

from services.user_service import (
    build_csv_template,
    bulk_create_users_from_csv,
    export_users_csv,
    get_user,
    parse_csv,
    get_user_by_username,
)


# ---------------------------------------------------------------------------
# Service layer
# ---------------------------------------------------------------------------


SAMPLE_CSV = """username,password,display_name,department_code,role,student_id,email,phone,year_enrolled,class_name,status
u001,abcd1234,張三,CS,student,111210001,u001@nku.edu.tw,0912000001,111,資工一A,active
u002,abcd1234,李四,EE,student,111220001,u002@nku.edu.tw,0912000002,111,電機一A,active
T100,abcd1234,王老師,CS,teacher,,t100@nku.edu.tw,082313100,,,active
"""


def test_parse_csv_basic():
    rows = parse_csv(SAMPLE_CSV)
    assert len(rows) == 3
    assert rows[0]["username"] == "u001"
    assert rows[0]["department_code"] == "CS"
    assert rows[1]["role"] == "student"
    assert rows[2]["role"] == "teacher"


def test_parse_csv_handles_bom():
    rows = parse_csv("\ufeff" + SAMPLE_CSV)
    assert rows[0]["username"] == "u001"


def test_parse_csv_handles_aliases():
    csv_text = "帳號,密碼,姓名,系所,信箱,學號\ns114210501,pwd,馮至豪,CS,f@x.com,114210501\n"
    rows = parse_csv(csv_text)
    assert rows[0]["username"] == "s114210501"
    assert rows[0]["password"] == "pwd"
    assert rows[0]["display_name"] == "馮至豪"
    assert rows[0]["department_code"] == "CS"
    assert rows[0]["email"] == "f@x.com"
    assert rows[0]["student_id"] == "114210501"


def test_parse_csv_skips_blank_rows():
    csv_text = "username,password,display_name\na,1,A\n\n\nb,2,B\n\n"
    rows = parse_csv(csv_text)
    assert len(rows) == 2


def test_build_csv_template_includes_bom_and_sample():
    tpl = build_csv_template()
    assert tpl.startswith("\ufeff")
    assert "username" in tpl
    assert "department_code" in tpl


def test_bulk_create_users_from_csv_happy_path(app, db):
    result = bulk_create_users_from_csv(db, SAMPLE_CSV)
    assert result["total"] == 3
    assert result["created"] == 3
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert all(r["status"] == "created" for r in result["results"])
    # verify in DB
    u = get_user_by_username(db, "u001")
    assert u is not None
    assert u["display_name"] == "張三"
    assert u["dept_code"] == "CS"
    assert u["year_enrolled"] == 111


def test_bulk_create_skip_duplicates(app, db):
    bulk_create_users_from_csv(db, SAMPLE_CSV)
    # Re-import same CSV -> all skipped
    result = bulk_create_users_from_csv(db, SAMPLE_CSV, skip_duplicates=True)
    assert result["created"] == 0
    assert result["skipped"] == 3
    assert all(r["status"] == "skipped" for r in result["results"])


def test_bulk_create_unknown_department_reported(app, db):
    # Only change the first row's department to an unknown code.
    bad_csv = SAMPLE_CSV.replace("u001,abcd1234,張三,CS,student", "u001,abcd1234,張三,XYZ99,student", 1)
    result = bulk_create_users_from_csv(db, bad_csv)
    assert result["errors"] == 1
    assert result["created"] == 2
    assert "系所代碼" in result["results"][0]["error"]


def test_bulk_create_validation_error_doesnt_abort_batch(app, db):
    bad_csv = """username,password,display_name,department_code,role
good,abcd1234,Good One,CS,student
empty_pwd,abcd1234,,CS,student
,x,No Name,CS,student
another_ok,abcd1234,Another,EE,student
"""
    result = bulk_create_users_from_csv(db, bad_csv)
    assert result["created"] == 2
    assert result["errors"] == 2
    err_rows = [r for r in result["results"] if r["status"] == "error"]
    assert all("row" in r for r in err_rows)


def test_bulk_create_with_default_password(app, db):
    csv_text = """username,display_name,department_code,role
a1,測試一,CS,student
a2,測試二,EE,student
"""
    result = bulk_create_users_from_csv(db, csv_text, default_password="default-pwd-1234")
    assert result["created"] == 2
    u = get_user_by_username(db, "a1")
    assert u is not None


def test_export_users_csv_round_trip(app, db):
    bulk_create_users_from_csv(db, SAMPLE_CSV)
    csv_text = export_users_csv(db)
    assert csv_text.startswith("\ufeff")
    rows = parse_csv(csv_text)
    # Export header excludes `password` (sensitive) — 11 cols not 12
    assert "password" not in rows[0]
    usernames = {r["username"] for r in rows}
    assert {"u001", "u002", "T100"}.issubset(usernames)


def test_export_csv_filter_by_role(app, db):
    bulk_create_users_from_csv(db, SAMPLE_CSV)
    csv_text = export_users_csv(db, role="teacher")
    rows = parse_csv(csv_text)
    assert all(r["role"] == "teacher" for r in rows)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def test_download_template_endpoint(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.get("/api/admin/users/template.csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers["Content-Type"]
    body = res.get_data(as_text=True)
    assert body.startswith("\ufeff")
    assert "department_code" in body


def test_export_endpoint(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.get("/api/admin/users/export.csv")
    assert res.status_code == 200
    assert res.headers["Content-Disposition"].startswith("attachment")


def test_import_endpoint_multipart(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    data = {"file": (io.BytesIO(SAMPLE_CSV.encode("utf-8")), "users.csv")}
    res = client.post("/api/admin/users/import", data=data, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()
    assert body["created"] == 3
    assert body["errors"] == 0


def test_import_endpoint_text_body(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.post("/api/admin/users/import", data=SAMPLE_CSV, content_type="text/csv")
    assert res.status_code == 200
    assert res.get_json()["created"] == 3


def test_import_endpoint_json(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.post("/api/admin/users/import", json={"csv": SAMPLE_CSV})
    assert res.status_code == 200
    assert res.get_json()["created"] == 3


def test_import_endpoint_requires_auth(app):
    client = app.test_client()
    res = client.post("/api/admin/users/import", data=SAMPLE_CSV, content_type="text/csv")
    assert res.status_code == 401


def test_import_empty_csv_rejected(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.post("/api/admin/users/import", data="", content_type="text/csv")
    assert res.status_code == 400


def test_import_partial_failure(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    mixed = """username,password,display_name,department_code,role
new_one,abcd1234,OK,CS,student
empty_pwd,abcd1234,,CS,student
no_dept,abcd1234,X,UNKNOWN_X,student
"""
    res = client.post("/api/admin/users/import", data=mixed, content_type="text/csv")
    body = res.get_json()
    assert body["created"] == 1
    assert body["errors"] == 2
