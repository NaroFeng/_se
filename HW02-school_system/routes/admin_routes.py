"""Admin API: menu CRUD + announcement CMS + user/department management."""
from flask import Blueprint, Response, current_app, jsonify, request

from models import get_db
from services.announcement_service import (
    delete_announcement,
    list_announcements,
    upsert_announcement,
)
from services.auth_service import get_current_user
from services.department_service import (
    DepartmentValidationError,
    create_department,
    delete_department,
    get_department,
    list_departments,
    update_department,
)
from services.menu_service import (
    MenuValidationError,
    build_menu_tree,
    create_menu_item,
    delete_menu_item,
    fetch_all_menu_items,
    get_menu_item,
    update_menu_item,
)
from services.user_service import (
    UserValidationError,
    build_csv_template,
    bulk_create_users_from_csv,
    create_user,
    delete_user,
    export_users_csv,
    get_user,
    list_users,
    reset_password,
    update_user,
)

bp = Blueprint("admin_api", __name__, url_prefix="/api/admin")


def _require_admin():
    db = get_db()
    user = get_current_user(db)
    if not user:
        return None, (jsonify({"error": "unauthorized"}), 401)
    if user["role"] != "admin":
        return None, (jsonify({"error": "forbidden"}), 403)
    return user, None


@bp.get("/ping")
def ping():
    user, err = _require_admin()
    if err:
        return err
    return jsonify({"ok": True, "user": user, "message": "admin api ready"})


# --- Menu CRUD -------------------------------------------------------------


@bp.get("/menu")
def admin_menu_list():
    user, err = _require_admin()
    if err:
        return err
    items = fetch_all_menu_items(get_db())
    return jsonify({"menu": build_menu_tree(items)})


@bp.post("/menu")
def admin_menu_create():
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = create_menu_item(
            get_db(),
            label=payload.get("label", ""),
            parent_id=payload.get("parent_id"),
            route=payload.get("route"),
            icon=payload.get("icon"),
            sort_order=payload.get("sort_order", 0),
            required_role=payload.get("required_role", "student"),
        )
    except MenuValidationError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "item": item}), 201


@bp.put("/menu/<int:item_id>")
def admin_menu_update(item_id: int):
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = update_menu_item(get_db(), item_id, payload)
    except MenuValidationError as e:
        return jsonify({"error": str(e)}), 400
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "item": item})


@bp.delete("/menu/<int:item_id>")
def admin_menu_delete(item_id: int):
    user, err = _require_admin()
    if err:
        return err
    ok = delete_menu_item(get_db(), item_id)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# --- Announcement CMS ------------------------------------------------------


@bp.post("/announcements")
def admin_announcement_upsert():
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    slug = (payload.get("slug") or "").strip()
    title = (payload.get("title") or "").strip()
    if not slug:
        return jsonify({"error": "slug 不可為空"}), 400
    if not title:
        return jsonify({"error": "title 不可為空"}), 400
    item = upsert_announcement(
        get_db(),
        slug=slug,
        title=title,
        category=(payload.get("category") or "一般").strip(),
        content=(payload.get("content") or ""),
        issued_at=(payload.get("issued_at") or "").strip(),
        author=(payload.get("author") or user["display_name"]).strip(),
    )
    return jsonify({"ok": True, "announcement": item})


@bp.delete("/announcements/<slug>")
def admin_announcement_delete(slug: str):
    user, err = _require_admin()
    if err:
        return err
    ok = delete_announcement(get_db(), slug)
    if not ok:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


@bp.get("/announcements")
def admin_announcement_list():
    user, err = _require_admin()
    if err:
        return err
    return jsonify({"announcements": list_announcements(get_db())})


# --- User Management -------------------------------------------------------


@bp.get("/users")
def admin_users_list():
    user, err = _require_admin()
    if err:
        return err
    search = request.args.get("q")
    role = request.args.get("role")
    status = request.args.get("status")
    department_id = request.args.get("department_id", type=int)
    year_enrolled = request.args.get("year_enrolled", type=int)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    result = list_users(
        get_db(),
        search=search,
        role=role,
        status=status,
        department_id=department_id,
        year_enrolled=year_enrolled,
        page=page,
        per_page=per_page,
        current_academic_year=current_app.config["ACADEMIC_YEAR"],
    )
    return jsonify(result)


@bp.get("/users/<int:user_id>")
def admin_users_get(user_id: int):
    user, err = _require_admin()
    if err:
        return err
    item = get_user(get_db(), user_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify({"user": item})


@bp.post("/users")
def admin_users_create():
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = create_user(get_db(), payload)
    except UserValidationError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "user": item}), 201


@bp.put("/users/<int:user_id>")
def admin_users_update(user_id: int):
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = update_user(get_db(), user_id, payload)
    except UserValidationError as e:
        return jsonify({"error": str(e)}), 400
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "user": item})


@bp.delete("/users/<int:user_id>")
def admin_users_delete(user_id: int):
    user, err = _require_admin()
    if err:
        return err
    if user["id"] == user_id:
        return jsonify({"error": "不能刪除自己"}), 400
    ok, msg = delete_user(get_db(), user_id)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg})


@bp.post("/users/<int:user_id>/reset-password")
def admin_users_reset_password(user_id: int):
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = reset_password(get_db(), user_id, payload.get("new_password", ""))
    except UserValidationError as e:
        return jsonify({"error": str(e)}), 400
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "message": f"已重設 {item['username']} 的密碼"})


# --- Bulk import / export -------------------------------------------------


@bp.get("/users/template.csv")
def admin_users_template():
    user, err = _require_admin()
    if err:
        return err
    csv_text = build_csv_template()
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="users-template.csv"',
        },
    )


@bp.get("/users/export.csv")
def admin_users_export():
    user, err = _require_admin()
    if err:
        return err
    role = request.args.get("role")
    status = request.args.get("status")
    department_id = request.args.get("department_id", type=int)
    csv_text = export_users_csv(
        get_db(), role=role, status=status, department_id=department_id
    )
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="users-export.csv"',
        },
    )


@bp.post("/users/import")
def admin_users_import():
    """Bulk import users from a CSV upload.

    Accepts either:
      * multipart/form-data with a `file` field, OR
      * `text/csv` body, OR
      * JSON body with `{"csv": "..."}`
    """
    admin, err = _require_admin()
    if err:
        return err

    csv_text = ""
    if request.files.get("file"):
        csv_text = request.files["file"].read().decode("utf-8", errors="replace")
    elif request.is_json:
        csv_text = (request.get_json(silent=True) or {}).get("csv", "")
    else:
        csv_text = request.get_data(as_text=True) or ""

    if not csv_text.strip():
        return jsonify({"error": "未收到 CSV 內容"}), 400

    default_pw = request.args.get("default_password") or request.form.get("default_password")
    skip_dup = (request.args.get("skip_duplicates", "1") not in ("0", "false", "False"))

    result = bulk_create_users_from_csv(
        get_db(), csv_text,
        default_password=default_pw,
        skip_duplicates=skip_dup,
    )
    return jsonify({"ok": True, **result})


# --- Department Management -------------------------------------------------


@bp.get("/departments")
def admin_departments_list():
    user, err = _require_admin()
    if err:
        return err
    return jsonify({"departments": list_departments(get_db())})


@bp.post("/departments")
def admin_departments_create():
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = create_department(
            get_db(),
            code=payload.get("code", ""),
            name=payload.get("name", ""),
            short_name=payload.get("short_name"),
            sort_order=payload.get("sort_order", 0),
        )
    except DepartmentValidationError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "department": item}), 201


@bp.put("/departments/<int:dept_id>")
def admin_departments_update(dept_id: int):
    user, err = _require_admin()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        item = update_department(get_db(), dept_id, payload)
    except DepartmentValidationError as e:
        return jsonify({"error": str(e)}), 400
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True, "department": item})


@bp.delete("/departments/<int:dept_id>")
def admin_departments_delete(dept_id: int):
    user, err = _require_admin()
    if err:
        return err
    ok, msg = delete_department(get_db(), dept_id)
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg})