"""HTTP routes (API + pages)."""
from .menu_routes import bp as menu_bp
from .auth_routes import bp as auth_bp
from .announcement_routes import bp as announcement_bp
from .admin_routes import bp as admin_bp
from .page_routes import bp as page_bp
from .page_partial_routes import bp as partial_bp

__all__ = ["menu_bp", "auth_bp", "announcement_bp", "admin_bp", "page_bp", "partial_bp"]