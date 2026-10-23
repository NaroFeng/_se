"""Menu API."""
from flask import Blueprint, jsonify

from models import get_db
from services.auth_service import get_current_user
from services.menu_service import fetch_all_menu_items, filter_menu_by_role

bp = Blueprint("menu_api", __name__, url_prefix="/api")


@bp.get("/menu")
def get_menu():
    """Return a flat list of menu items (client builds the tree).

    Each item has `id`, `parent_id`, `label`, `route`, `icon`, `sort_order`,
    `required_role`. The client (static/js/utils/tree.js:buildTree) is
    responsible for nesting by parent_id.
    """
    db = get_db()
    user = get_current_user(db)
    if user is None:
        return jsonify({"error": "unauthorized"}), 401
    items = fetch_all_menu_items(db)
    visible = filter_menu_by_role(items, user["role"])
    return jsonify({
        "role": user["role"],
        "user": user,
        "menu": visible,
    })