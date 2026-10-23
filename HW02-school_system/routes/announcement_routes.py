"""Announcement API (read-only in v0.1.0, CMS lands in v0.4.0)."""
from flask import Blueprint, jsonify

from models import get_db
from services.announcement_service import get_announcement, list_announcements
from services.auth_service import get_current_user

bp = Blueprint("announcement_api", __name__, url_prefix="/api/announcements")


def _require_user():
    db = get_db()
    user = get_current_user(db)
    if not user:
        return None, (jsonify({"error": "unauthorized"}), 401)
    return user, None


@bp.get("")
def list_all():
    _, err = _require_user()
    if err:
        return err
    items = list_announcements(get_db())
    return jsonify({"announcements": items})


@bp.get("/<slug>")
def get_one(slug: str):
    _, err = _require_user()
    if err:
        return err
    item = get_announcement(get_db(), slug)
    if not item:
        return jsonify({"error": "not found"}), 404
    return jsonify({"announcement": item})