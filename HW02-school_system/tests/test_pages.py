"""Page rendering tests (HTML smoke)."""
def test_index_redirects_anonymous_to_login(app):
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 302
    assert "/login" in res.headers.get("Location", "")


def test_index_renders_for_anonymous(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "金門大學" in body
    assert "校務資訊系統" in body
    assert "115學年度第1學期" in body
    # sidebar container present but contents are JS-rendered
    assert 'id="sidebar-nav"' in body
    assert 'id="sidebar-search"' in body
    # header buttons
    assert "修改密碼" in body
    assert "隱藏選單" in body
    assert "登出" in body


def test_index_renders_user_info_when_logged_in(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "馮至豪" in body
    assert "資工二" in body


def test_login_page_renders(app):
    client = app.test_client()
    res = client.get("/login")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "請輸入您的校務帳號密碼登入" in body
    assert "s114210501" in body and "pass1234" in body


def test_static_logo_served(app):
    client = app.test_client()
    res = client.get("/static/img/logo.svg")
    assert res.status_code == 200
    assert b"<svg" in res.data


def test_admin_ping_rejects_student(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/api/admin/ping")
    assert res.status_code == 403


def test_admin_ping_allows_admin(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.get("/api/admin/ping")
    assert res.status_code == 200
    assert res.get_json()["ok"] is True