"""Services package: business logic."""
from .menu_service import build_menu_tree, filter_menu_by_role
from .announcement_service import list_announcements, get_announcement, upsert_announcement
from .auth_service import (
    authenticate,
    get_current_user,
    login_user,
    logout_user,
    switch_role_user,
    change_password,
)
from .user_service import (
    compute_grade,
    list_users,
    get_user,
    create_user,
    update_user,
    delete_user,
    reset_password,
)
from .department_service import (
    list_departments,
    get_department,
    create_department,
    update_department,
    delete_department,
)

__all__ = [
    "build_menu_tree",
    "filter_menu_by_role",
    "list_announcements",
    "get_announcement",
    "upsert_announcement",
    "authenticate",
    "get_current_user",
    "login_user",
    "logout_user",
    "switch_role_user",
    "change_password",
    "compute_grade",
    "list_users",
    "get_user",
    "create_user",
    "update_user",
    "delete_user",
    "reset_password",
    "list_departments",
    "get_department",
    "create_department",
    "update_department",
    "delete_department",
]