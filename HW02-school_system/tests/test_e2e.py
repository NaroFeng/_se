"""End-to-end smoke test simulating a full user flow."""
def test_full_student_flow(app):
    client = app.test_client()

    # anonymous cannot access menu
    assert client.get("/api/menu").status_code == 401

    # login as student
    res = client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    assert res.status_code == 200
    user = res.get_json()["user"]
    assert user["role"] == "student"

    # fetch menu (student-visible)
    res = client.get("/api/menu")
    menu = res.get_json()["menu"]
    labels = {n["label"] for n in menu}
    assert "公告訊息" in labels
    assert "系統管理" not in labels  # admin-only

    # switch role to admin
    res = client.post("/api/auth/switch-role", json={"role": "admin"})
    assert res.status_code == 200
    assert res.get_json()["user"]["role"] == "admin"

    # menu now includes admin nodes
    res = client.get("/api/menu")
    labels = {n["label"] for n in res.get_json()["menu"]}
    assert "系統管理" in labels

    # read announcement partial via AJAX
    res = client.get("/page/announcement/course-selection")
    assert res.status_code == 200
    assert "<h1>" in res.get_data(as_text=True)

    # admin cms
    res = client.get("/page/admin/menu")
    assert res.status_code == 200
    assert "選單管理" in res.get_data(as_text=True)

    # logout
    res = client.post("/api/auth/logout")
    assert res.status_code == 200

    # back to anonymous
    assert client.get("/api/menu").status_code == 401


def test_full_password_change_then_relogin(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "teacher01", "password": "pass1234"})

    # change password
    res = client.post("/api/auth/change-password", json={
        "old_password": "pass1234",
        "new_password": "newpass9999",
    })
    assert res.status_code == 200

    client.post("/api/auth/logout")

    # old password no longer works
    assert client.post("/api/auth/login", json={"username": "teacher01", "password": "pass1234"}).status_code == 401
    # new password works
    assert client.post("/api/auth/login", json={"username": "teacher01", "password": "newpass9999"}).status_code == 200


def test_admin_menu_crud_visible_to_student_after_switch(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    # create a new menu node as admin
    res = client.post("/api/admin/menu", json={
        "label": "Demo 節點",
        "parent_id": None,
        "route": "/page/demo",
        "icon": "doc",
        "sort_order": 999,
        "required_role": "student",
    })
    assert res.status_code == 201
    new_id = res.get_json()["item"]["id"]

    # switch role to student -> should see Demo 節點
    client.post("/api/auth/switch-role", json={"role": "student"})
    res = client.get("/api/menu")
    labels = flatten_labels(res.get_json()["menu"])
    assert "Demo 節點" in labels

    # delete it
    client.post("/api/auth/switch-role", json={"role": "admin"})
    res = client.delete(f"/api/admin/menu/{new_id}")
    assert res.status_code == 200

    client.post("/api/auth/switch-role", json={"role": "student"})
    res = client.get("/api/menu")
    labels = flatten_labels(res.get_json()["menu"])
    assert "Demo 節點" not in labels


def flatten_labels(nodes):
    out = []
    for n in nodes:
        out.append(n["label"])
        out.extend(flatten_labels(n.get("children", [])))
    return out