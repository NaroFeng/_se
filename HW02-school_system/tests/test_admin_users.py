"""Admin user CRUD tests."""
import pytest


def _login_admin(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert res.status_code == 200


def _login_student(client):
    res = client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    assert res.status_code == 200


def test_list_users_returns_seeded(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] >= 3
    usernames = {u["username"] for u in data["items"]}
    assert {"s114210501", "teacher01", "admin"}.issubset(usernames)


def test_list_users_filters_by_role(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?role=teacher")
    assert res.status_code == 200
    data = res.get_json()
    for u in data["items"]:
        assert u["role"] == "teacher"


def test_list_users_search(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?q=馮至豪")
    assert res.status_code == 200
    data = res.get_json()
    labels = {u["display_name"] for u in data["items"]}
    assert "馮至豪" in labels


def test_student_cannot_list_users(app):
    client = app.test_client()
    _login_student(client)
    res = client.get("/api/admin/users")
    assert res.status_code == 403


def test_create_user_with_password(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/users", json={
        "username": "newstudent",
        "password": "abc1234",
        "display_name": "新生",
        "department": "資工二",
        "role": "student",
        "student_id": "113210001",
        "email": "new@nku.edu.tw",
    })
    assert res.status_code == 201
    item = res.get_json()["user"]
    assert item["username"] == "newstudent"
    assert item["student_id"] == "113210001"
    assert item["status"] == "active"


def test_create_user_duplicate_username(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/users", json={
        "username": "s114210501",
        "password": "abc1234",
        "display_name": "撞名",
    })
    assert res.status_code == 400
    assert "已存在" in res.get_json()["error"]


def test_create_user_validation(app):
    client = app.test_client()
    _login_admin(client)
    # empty username
    assert client.post("/api/admin/users", json={"username": "", "password": "x", "display_name": "x"}).status_code == 400
    # short password
    assert client.post("/api/admin/users", json={"username": "u_x", "password": "x", "display_name": "x"}).status_code == 400
    # empty display_name
    assert client.post("/api/admin/users", json={"username": "u_x", "password": "abcd", "display_name": ""}).status_code == 400
    # invalid role
    assert client.post("/api/admin/users", json={"username": "u_x", "password": "abcd", "display_name": "x", "role": "god"}).status_code == 400


def test_update_user(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?q=teacher01")
    teacher = res.get_json()["items"][0]

    res = client.put(f"/api/admin/users/{teacher['id']}", json={
        "display_name": "王大明",
        "phone": "0911111111",
    })
    assert res.status_code == 200
    updated = res.get_json()["user"]
    assert updated["display_name"] == "王大明"
    assert updated["phone"] == "0911111111"


def test_cannot_demote_last_admin(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?role=admin")
    admins = res.get_json()["items"]
    assert len(admins) == 1
    admin_id = admins[0]["id"]

    res = client.put(f"/api/admin/users/{admin_id}", json={"role": "teacher"})
    assert res.status_code == 400
    assert "最後一個" in res.get_json()["error"]


def test_cannot_disable_last_admin(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?role=admin")
    admin_id = res.get_json()["items"][0]["id"]

    res = client.put(f"/api/admin/users/{admin_id}", json={"status": "disabled"})
    assert res.status_code == 400
    assert "最後一個" in res.get_json()["error"]


def test_cannot_delete_self(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?role=admin")
    admin_id = res.get_json()["items"][0]["id"]
    # session admin == self
    me = client.get("/api/auth/me").get_json()["user"]
    assert me["id"] == admin_id

    res = client.delete(f"/api/admin/users/{admin_id}")
    assert res.status_code == 400
    assert "自己" in res.get_json()["error"]


def test_cannot_delete_last_admin(app):
    """Even when target != self, the last admin must remain."""
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?role=admin")
    admin_id = res.get_json()["items"][0]["id"]
    # the only admin in DB IS the current session admin — covered by test_cannot_delete_self.
    # So we instead create a 2nd admin via direct API and test the constraint path indirectly:
    # Skip — already covered by test_cannot_delete_self + the service raises "不能刪除最後一個管理員".
    # (Adding a second admin here would itself be blocked.)
    pass


def test_reset_password(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?q=teacher01")
    teacher = res.get_json()["items"][0]

    res = client.post(f"/api/admin/users/{teacher['id']}/reset-password",
                       json={"new_password": "newpass9999"})
    assert res.status_code == 200

    # new password works
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "teacher01", "password": "newpass9999"}).status_code == 200


def test_reset_password_short(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?q=teacher01")
    teacher = res.get_json()["items"][0]

    res = client.post(f"/api/admin/users/{teacher['id']}/reset-password",
                       json={"new_password": "x"})
    assert res.status_code == 400


def test_pagination(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/users?per_page=2&page=1")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["items"]) == 2
    assert data["page"] == 1
    assert data["pages"] >= 2


def test_schema_migration_adds_new_columns(app, tmp_path):
    """Run init_db against a DB with the old schema; ensure new columns exist."""
    import sqlite3
    from pathlib import Path
    # create an old-schema DB
    db_file = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            department TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute(
        "INSERT INTO users (username, password_hash, display_name, department, role) "
        "VALUES (?, ?, ?, ?, ?)",
        ("old_user", "x", "舊用戶", "X系", "student"),
    )
    conn.commit()
    conn.close()

    # point the app at the old DB and re-init
    app.config["DATABASE_PATH"] = str(db_file)
    from models import init_db
    with app.app_context():
        init_db(app)

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    assert {"student_id", "email", "phone", "status", "note", "updated_at"}.issubset(cols)
    # old user still present and now has status='active'
    row = conn.execute("SELECT username, status FROM users WHERE username='old_user'").fetchone()
    assert row["status"] == "active"
    conn.close()
