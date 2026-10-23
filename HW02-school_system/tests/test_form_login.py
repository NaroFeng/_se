"""Form-based fallback login (works without JS)."""
def test_login_form_post_success(app):
    client = app.test_client()
    res = client.post("/login", data={"username": "s114210501", "password": "pass1234"}, follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["Location"].endswith("/")
    # session set
    res = client.get("/api/auth/me")
    assert res.status_code == 200


def test_login_form_post_wrong_password(app):
    client = app.test_client()
    res = client.post("/login", data={"username": "s114210501", "password": "wrong"}, follow_redirects=False)
    assert res.status_code == 401
    body = res.get_data(as_text=True)
    assert "帳號或密碼錯誤" in body
    assert res.request.path == "/login"


def test_login_form_post_keeps_username(app):
    client = app.test_client()
    res = client.post("/login", data={"username": "s114210501", "password": "wrong"})
    body = res.get_data(as_text=True)
    # username value is preserved in re-rendered form
    assert 'value="s114210501"' in body


def test_get_logout_clears_session(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    assert client.get("/api/auth/me").status_code == 200
    res = client.get("/logout", follow_redirects=False)
    assert res.status_code == 302
    assert client.get("/api/auth/me").status_code == 401