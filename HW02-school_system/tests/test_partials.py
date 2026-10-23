"""Partial page route tests."""
def test_home_partial_renders(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/home")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "歡迎使用" in body
    assert "最新公告" in body
    assert "選課公告" in body


def test_announcement_detail_partial_renders(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/announcement/course-selection")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "<h1>" in body
    assert "選課公告" in body
    # markdown -> HTML
    assert "<h2>" in body or "<h3>" in body
    assert "<ol>" in body or "<ul>" in body


def test_announcement_detail_404(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/announcement/no-such-slug")
    assert res.status_code == 404


def test_courses_partial(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/courses")
    assert res.status_code == 200
    assert "資料結構" in res.get_data(as_text=True)


def test_grades_partial(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/grades")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "學期平均" in body


def test_partials_require_auth(app):
    client = app.test_client()
    res = client.get("/page/home")
    assert res.status_code == 401


def test_admin_page_blocks_non_admin(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/page/admin/menu")
    assert res.status_code == 200
    assert "僅限管理員" in res.get_data(as_text=True)


def test_admin_page_renders_for_admin(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.get("/page/admin/menu")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "選單管理" in body
    assert "僅限管理員" not in body