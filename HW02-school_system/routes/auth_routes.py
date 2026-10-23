"""Authentication API."""
from flask import Blueprint, jsonify, request

from models import get_db
from services.auth_service import (
    authenticate,
    change_password,
    get_current_user,
    login_user,
    logout_user,
    switch_role_user,
)

bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")


def _require_auth_response():
    db = get_db()
    user = get_current_user(db)
    if not user:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return user, None


@bp.post("/login")
def login():
    db = get_db()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = authenticate(db, username, password)
    if not user:
        return jsonify({"error": "帳號或密碼錯誤"}), 401
    login_user(user)
    return jsonify({"ok": True, "user": user})


@bp.post("/logout")
def logout():
    logout_user()
    return jsonify({"ok": True})


@bp.get("/me")
def me():
    user, err = _require_auth_response()
    if err:
        return err
    return jsonify({"user": user})


@bp.post("/switch-role")
def switch_role():
    user, err = _require_auth_response()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    role = data.get("role")
    updated = switch_role_user(role)
    if updated is None:
        return jsonify({"error": "無效的角色"}), 400
    return jsonify({"ok": True, "user": updated})


@bp.post("/change-password")
def change_pw():
    db = get_db()
    user, err = _require_auth_response()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    ok, msg = change_password(
        db,
        user["username"],
        data.get("old_password", ""),
        data.get("new_password", ""),
    )
    if not ok:
        return jsonify({"error": msg}), 400
    return jsonify({"ok": True, "message": msg})