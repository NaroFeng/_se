"""Page partial routes: return HTML fragments (no layout) for AJAX loading.

URL shape: /page/<path:subpath>

Two response modes:
  * AJAX (`X-Requested-With: fetch`) → raw HTML fragment for router.js to inject
  * Direct browser visit → full page (base layout + pre-rendered partial)
"""
from flask import Blueprint, abort, jsonify, render_template, request

from config import Config
from models import get_db
from services.announcement_service import get_announcement, list_announcements
from services.auth_service import get_current_user
from services.markdown import render_markdown
from services.menu_service import (
    build_menu_tree,
    fetch_all_menu_items,
    filter_menu_by_role,
)

bp = Blueprint("partial_pages", __name__, url_prefix="/page")


DEMO_COURSES = [
    {"code": "CS301", "name": "資料結構", "credits": 3, "teacher": "王小明", "time": "週二 34 / 週四 34"},
    {"code": "CS302", "name": "演算法概論", "credits": 3, "teacher": "林大華", "time": "週一 56 / 週三 56"},
    {"code": "CS303", "name": "作業系統", "credits": 3, "teacher": "陳怡君", "time": "週五 23"},
    {"code": "MA201", "name": "工程數學", "credits": 3, "teacher": "張志明", "time": "週一 34 / 週四 34"},
]

DEMO_GRADES = [
    {"name": "資料結構", "credits": 3, "score": 87, "grade": "A-"},
    {"name": "演算法概論", "credits": 3, "score": 92, "grade": "A"},
    {"name": "作業系統", "credits": 3, "score": 78, "grade": "B"},
    {"name": "工程數學", "credits": 3, "score": 81, "grade": "B+"},
]


def _is_ajax() -> bool:
    return request.headers.get("X-Requested-With") == "fetch"


def _require_user():
    user = get_current_user(get_db())
    if not user:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return user, None


def _bootstrap_context() -> dict:
    db = get_db()
    user = get_current_user(db)
    role = (user or {}).get("role", "student")
    items = fetch_all_menu_items(db)
    visible = filter_menu_by_role(items, role)
    tree = build_menu_tree(visible)
    return {
        "user": user,
        "menu_tree": tree,
        "school_name": Config.SCHOOL_NAME,
        "system_name": Config.SYSTEM_NAME,
        "semester_label": Config.SEMESTER_LABEL,
    }


def _lookup_label(route: str) -> tuple[str, str | None]:
    """Find the menu label & icon for a /page/<route>; returns (label, icon)."""
    items = fetch_all_menu_items(get_db())
    target = f"/page/{route}"
    for it in items:
        if it["route"] == target:
            return it["label"], it["icon"]
    return route, None


def _full_page(subpath: str):
    """Render the full index page with this subpath embedded as initial content."""
    label, icon = _lookup_label(subpath)
    ctx = _bootstrap_context()
    ctx["initial_partial"] = _render_partial_for(subpath)
    ctx["initial_route"] = f"/page/{subpath}"
    return render_template("index_with_partial.html", **ctx)


def _render_partial_for(subpath: str):
    """Render the partial HTML string for embedding into the full page."""
    # Dispatch by first path segment.
    parts = subpath.split("/", 1)
    head = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    user, err = _require_user()
    if err:
        return "<p>未登入</p>"

    if head == "home":
        return render_template("pages/home.html", user=user, announcements=list_announcements(get_db())[:3])
    if head == "announcements":
        return render_template("pages/announcement_list.html", user=user, announcements=list_announcements(get_db()))
    if head == "announcement" and rest:
        item = get_announcement(get_db(), rest)
        if not item:
            return "<p>找不到公告</p>"
        return render_template("pages/announcement_detail.html", user=user, announcement=item,
                               html_content=render_markdown(item["content"]))
    if head == "admin" and rest == "menu":
        return render_template("pages/admin_menu.html", user=user)
    if head == "admin" and rest == "announcements":
        return render_template("pages/admin_announcements.html", user=user)
    if head == "courses":
        return render_template("pages/courses.html", user=user, demo_courses=DEMO_COURSES)
    if head == "grades":
        avg = round(sum(g["score"] for g in DEMO_GRADES) / len(DEMO_GRADES), 1)
        return render_template("pages/grades.html", user=user, demo_grades=DEMO_GRADES, demo_avg=avg)

    label, icon = _lookup_label(subpath)
    return render_template("pages/placeholder.html", user=user,
                           route=f"/page/{subpath}", title=label, icon=icon)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@bp.get("/home")
def page_home():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("home")
    announcements = list_announcements(get_db())
    return render_template(
        "pages/home.html",
        user=user,
        announcements=announcements[:3],
        school_name=user.get("display_name", ""),
    )


@bp.get("/announcements")
def page_announcement_list():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("announcements")
    items = list_announcements(get_db())
    return render_template("pages/announcement_list.html", user=user, announcements=items, school_name="金門大學")


@bp.get("/announcement/<slug>")
def page_announcement_detail(slug: str):
    user, err = _require_user()
    if err:
        return err
    item = get_announcement(get_db(), slug)
    if not item:
        abort(404)
    if not _is_ajax():
        return _full_page(f"announcement/{slug}")
    html = render_markdown(item["content"])
    return render_template(
        "pages/announcement_detail.html",
        user=user,
        announcement=item,
        html_content=html,
    )


@bp.get("/admin/menu")
def page_admin_menu():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("admin/menu")
    return render_template("pages/admin_menu.html", user=user)


@bp.get("/admin/announcements")
def page_admin_announcements():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("admin/announcements")
    return render_template("pages/admin_announcements.html", user=user)


@bp.get("/admin/users")
def page_admin_users():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("admin/users")
    return render_template("pages/admin_users.html", user=user)


@bp.get("/courses")
def page_courses():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("courses")
    return render_template("pages/courses.html", user=user, demo_courses=DEMO_COURSES)


@bp.get("/grades")
def page_grades():
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page("grades")
    avg = round(sum(g["score"] for g in DEMO_GRADES) / len(DEMO_GRADES), 1)
    return render_template("pages/grades.html", user=user, demo_grades=DEMO_GRADES, demo_avg=avg)


@bp.get("/<path:route>")
def page_placeholder(route: str):
    user, err = _require_user()
    if err:
        return err
    if not _is_ajax():
        return _full_page(route)
    label, icon = _lookup_label(route)
    return render_template(
        "pages/placeholder.html",
        user=user,
        route=f"/page/{route}",
        title=label,
        icon=icon,
    )
