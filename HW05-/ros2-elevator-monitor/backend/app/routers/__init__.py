"""API 路由模組。"""

from .floors import router as floors_router
from .inspections import router as inspections_router
from .system import router as system_router

__all__ = ["floors_router", "inspections_router", "system_router"]