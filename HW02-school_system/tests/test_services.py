"""Service-layer unit tests."""
from services.auth_service import authenticate, change_password
from services.menu_service import (
    build_menu_tree,
    filter_menu_by_role,
)


def _login_as(client, username, password):
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200
    return res.get_json()


def test_login_success_and_me(app):
    client = app.test_client()
    data = _login_as(client, "s114210501", "pass1234")
    assert data["user"]["display_name"] == "馮至豪"
    assert data["user"]["role"] == "student"

    res = client.get("/api/auth/me")
    assert res.status_code == 200
    assert res.get_json()["user"]["username"] == "s114210501"


def test_login_wrong_password(app):
    client = app.test_client()
    res = client.post("/api/auth/login", json={"username": "s114210501", "password": "bad"})
    assert res.status_code == 401


def test_change_password_full_flow(app):
    client = app.test_client()
    _login_as(client, "s114210501", "pass1234")

    # wrong old password
    res = client.post("/api/auth/change-password", json={"old_password": "bad", "new_password": "abcd1234"})
    assert res.status_code == 400

    # success
    res = client.post("/api/auth/change-password", json={"old_password": "pass1234", "new_password": "abcd1234"})
    assert res.status_code == 200

    # logout then re-login with new password
    client.post("/api/auth/logout")
    res = client.post("/api/auth/login", json={"username": "s114210501", "password": "abcd1234"})
    assert res.status_code == 200


def test_change_password_too_short(app):
    client = app.test_client()
    _login_as(client, "s114210501", "pass1234")
    res = client.post("/api/auth/change-password", json={"old_password": "pass1234", "new_password": "x"})
    assert res.status_code == 400


def test_filter_menu_by_role_excludes_higher():
    items = [
        {"id": 1, "parent_id": None, "label": "A", "required_role": "student", "sort_order": 0},
        {"id": 2, "parent_id": None, "label": "B", "required_role": "teacher", "sort_order": 0},
        {"id": 3, "parent_id": None, "label": "C", "required_role": "admin", "sort_order": 0},
    ]
    assert [i["label"] for i in filter_menu_by_role(items, "student")] == ["A"]
    assert [i["label"] for i in filter_menu_by_role(items, "teacher")] == ["A", "B"]
    assert [i["label"] for i in filter_menu_by_role(items, "admin")] == ["A", "B", "C"]


def test_build_menu_tree_nests_children():
    flat = [
        {"id": 1, "parent_id": None, "label": "Root", "required_role": "student", "sort_order": 0, "children": []},
        {"id": 2, "parent_id": 1, "label": "Child", "required_role": "student", "sort_order": 0, "children": []},
        {"id": 3, "parent_id": None, "label": "Sibling", "required_role": "student", "sort_order": 1, "children": []},
    ]
    tree = build_menu_tree(flat)
    assert [n["label"] for n in tree] == ["Root", "Sibling"]
    assert [c["label"] for c in tree[0]["children"]] == ["Child"]


def test_menu_endpoint_returns_role_specific_tree(app):
    client = app.test_client()
    _login_as(client, "s114210501", "pass1234")
    res = client.get("/api/menu")
    assert res.status_code == 200
    data = res.get_json()
    labels = [n["label"] for n in data["menu"]]
    # admin-only items must not appear for student
    assert "系統管理" not in labels
    assert "教師專區" not in labels
    assert "公告訊息" in labels


def test_menu_endpoint_requires_auth(app):
    client = app.test_client()
    res = client.get("/api/menu")
    assert res.status_code == 401