"""Page routes: serve HTML templates (no JSON)."""
from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from config import Config
from models import get_db
from services.auth_service import authenticate, get_current_user, login_user
from services.menu_service import (
    build_menu_tree,
    fetch_all_menu_items,
    filter_menu_by_role,
)

bp = Blueprint("pages", __name__)


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


@bp.get("/")
def index():
    if get_current_user(get_db()) is None:
        return redirect(url_for("pages.login_page"))
    return render_template("index.html", **_bootstrap_context())


@bp.get("/login")
def login_page():
    return render_template("login.html", **_bootstrap_context())


@bp.get("/api/config")
def public_config():
    """Public read-only config the frontend needs (academic year, etc.)."""
    return jsonify({
        "academic_year": Config.ACADEMIC_YEAR,
        "school_name": Config.SCHOOL_NAME,
        "system_name": Config.SYSTEM_NAME,
        "semester_label": Config.SEMESTER_LABEL,
    })


@bp.post("/login")
def login_submit():
    """Form-based fallback login (works even if JS fails to load)."""
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    user = authenticate(get_db(), username, password)
    if not user:
        return render_template(
            "login.html",
            **_bootstrap_context(),
            login_error="帳號或密碼錯誤",
            login_username=username,
        ), 401
    login_user(user)
    return redirect(url_for("pages.index"))


@bp.get("/logout")
def logout_redirect():
    from services.auth_service import logout_user
    logout_user()
    return redirect(url_for("pages.login_page"))