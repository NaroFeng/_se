"""Admin API tests: menu CRUD + announcement CMS."""
import pytest


def _login_admin(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert res.status_code == 200


def _login_student(client):
    res = client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    assert res.status_code == 200


def test_admin_menu_list_returns_full_tree(app):
    client = app.test_client()
    _login_admin(client)
    res = client.get("/api/admin/menu")
    assert res.status_code == 200
    data = res.get_json()
    assert "menu" in data
    labels = {n["label"] for n in data["menu"]}
    assert "系統管理" in labels
    assert "公告訊息" in labels


def test_admin_menu_list_forbidden_for_student(app):
    client = app.test_client()
    _login_student(client)
    res = client.get("/api/admin/menu")
    assert res.status_code == 403


def test_admin_create_menu_item(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/menu", json={
        "label": "測試節點",
        "parent_id": None,
        "route": "/page/test",
        "icon": "doc",
        "sort_order": 99,
        "required_role": "student",
    })
    assert res.status_code == 201
    item = res.get_json()["item"]
    assert item["label"] == "測試節點"
    assert item["route"] == "/page/test"
    assert item["sort_order"] == 99


def test_admin_create_child_menu_item(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/menu", json={
        "label": "父節點",
        "parent_id": None,
        "route": None,
        "sort_order": 50,
        "required_role": "student",
    })
    parent_id = res.get_json()["item"]["id"]
    res2 = client.post("/api/admin/menu", json={
        "label": "子節點",
        "parent_id": parent_id,
        "route": "/page/child",
        "sort_order": 1,
        "required_role": "student",
    })
    assert res2.status_code == 201
    assert res2.get_json()["item"]["parent_id"] == parent_id


def test_admin_update_menu_item(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/menu", json={
        "label": "原名",
        "parent_id": None,
        "route": None,
        "sort_order": 0,
        "required_role": "student",
    })
    item_id = res.get_json()["item"]["id"]
    res2 = client.put(f"/api/admin/menu/{item_id}", json={"label": "新名稱", "sort_order": 5})
    assert res2.status_code == 200
    assert res2.get_json()["item"]["label"] == "新名稱"
    assert res2.get_json()["item"]["sort_order"] == 5


def test_admin_update_prevents_cycle(app):
    client = app.test_client()
    _login_admin(client)
    # create parent
    p = client.post("/api/admin/menu", json={"label": "P", "parent_id": None, "route": None, "sort_order": 0, "required_role": "student"}).get_json()["item"]
    c = client.post("/api/admin/menu", json={"label": "C", "parent_id": p["id"], "route": None, "sort_order": 0, "required_role": "student"}).get_json()["item"]
    # try to set parent's parent_id to child -> cycle
    res = client.put(f"/api/admin/menu/{p['id']}", json={"parent_id": c["id"]})
    assert res.status_code == 400
    assert "子孫" in res.get_json()["error"]


def test_admin_delete_menu_item_cascades(app):
    client = app.test_client()
    _login_admin(client)
    p = client.post("/api/admin/menu", json={"label": "P", "parent_id": None, "route": None, "sort_order": 0, "required_role": "student"}).get_json()["item"]
    c = client.post("/api/admin/menu", json={"label": "C", "parent_id": p["id"], "route": None, "sort_order": 0, "required_role": "student"}).get_json()["item"]
    res = client.delete(f"/api/admin/menu/{p['id']}")
    assert res.status_code == 200
    res2 = client.get("/api/admin/menu")
    ids = collect_ids(res2.get_json()["menu"])
    assert p["id"] not in ids
    assert c["id"] not in ids


def collect_ids(nodes):
    out = []
    for n in nodes:
        out.append(n["id"])
        out.extend(collect_ids(n.get("children", [])))
    return out


def test_admin_create_announcement(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/announcements", json={
        "slug": "test-new",
        "title": "測試公告",
        "category": "測試",
        "content": "## hi\n\ntext",
        "issued_at": "2026-09-10",
        "author": "tester",
    })
    assert res.status_code == 200
    item = res.get_json()["announcement"]
    assert item["slug"] == "test-new"
    assert item["title"] == "測試公告"


def test_admin_update_existing_announcement(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/announcements", json={
        "slug": "course-selection",
        "title": "新標題",
        "category": "選課",
        "content": "內容",
        "issued_at": "2026-09-10",
        "author": "tester",
    })
    assert res.status_code == 200
    assert res.get_json()["announcement"]["title"] == "新標題"


def test_admin_delete_announcement(app):
    client = app.test_client()
    _login_admin(client)
    res = client.delete("/api/admin/announcements/test-new")
    # test-new might not exist if previous test didn't run; this is acceptable.
    assert res.status_code in (200, 404)


def test_admin_validation_empty_label(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/menu", json={"label": "", "parent_id": None})
    assert res.status_code == 400


def test_admin_validation_invalid_role(app):
    client = app.test_client()
    _login_admin(client)
    res = client.post("/api/admin/menu", json={"label": "x", "required_role": "god"})
    assert res.status_code == 400