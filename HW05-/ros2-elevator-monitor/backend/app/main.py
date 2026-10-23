"""FastAPI 進入點：web-backend 容器主程式。

啟動流程：
    1. 等待 PostgreSQL 就緒
    2. （選用）依 ORM 模型建表
    3. 啟動背景輪詢：向 ros2-bridge 取得機器人狀態並寫入快取
    4. 註冊所有 API 路由
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.openapi.utils import get_openapi

from .config import settings
from .database import create_tables_if_needed, wait_for_database
from .routers import floors_router, inspections_router, system_router
from .services import ros_bridge
from .services.robot_state import robot_state_cache

# ---------------- 日誌格式 ----------------
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="[web-backend][%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("uvicorn.error")


async def poll_bridge_status(stop_event: asyncio.Event) -> None:
    """背景工作：定期向 ros2-bridge 輪詢狀態（heartbeat 未連上時的備援）。"""
    interval = settings.bridge_poll_interval
    logger.info("已啟動 ros2-bridge 狀態輪詢（每 %.1f 秒）", interval)

    while not stop_event.is_set():
        try:
            data = await ros_bridge.get_status()
            if data:
                robot_state_cache.update(data, source="poll")
                logger.debug("輪詢到最新狀態：%s", data.get("fsm_state"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("輪詢 ros2-bridge 狀態失敗：%s", exc)

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=interval)

    logger.info("ros2-bridge 狀態輪詢已停止")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """應用程式啟動/關閉生命週期。"""
    logger.info("=== %s v%s 啟動中 ===", settings.app_name, settings.app_version)

    # 1. 等待資料庫
    try:
        wait_for_database()
    except Exception as exc:  # noqa: BLE001
        logger.error("資料庫連線失敗，服務將以降級模式啟動：%s", exc)

    # 2. （選用）自動建表
    try:
        create_tables_if_needed()
    except Exception as exc:  # noqa: BLE001
        logger.warning("自動建表失敗：%s", exc)

    # 3. 背景輪詢 Bridge 狀態
    stop_event = asyncio.Event()
    poller = asyncio.create_task(poll_bridge_status(stop_event))

    yield

    # ---- 關閉 ----
    stop_event.set()
    poller.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poller
    await ros_bridge.close_client()
    logger.info("=== %s 已關閉 ===", settings.app_name)


# =====================================================================
# 應用程式實例
# =====================================================================
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "ROS 2 跨樓層巡檢機器人監控後台系統 - 業務邏輯與資料 API。\n\n"
        "* `floors`：樓層資訊、地圖路徑、電梯按鈕座標特徵\n"
        "* `inspections`：巡檢紀錄日誌與統計\n"
        "* `system`：健康檢查、機器人即時狀態、ROS 2 指令轉送"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------- CORS（前端經 Nginx 代理時仍可直連除錯）----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- API 文件相容性導向 ----------------
# 舊版把文件放在 /api/docs，這裡保留轉址，讓兩種網址都能開啟。
LEGACY_DOC_PATHS = {
    "/api/docs": "/docs",
    "/api/redoc": "/redoc",
}


@app.get("/api/docs", include_in_schema=False)
@app.get("/api/redoc", include_in_schema=False)
def legacy_docs(request: Request) -> RedirectResponse:
    return RedirectResponse(url=LEGACY_DOC_PATHS[request.url.path])


@app.get("/api/openapi.json", include_in_schema=False)
def legacy_openapi() -> JSONResponse:
    return JSONResponse(content=app.openapi())


# ---------------- 全域例外處理 ----------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未處理的例外 (%s %s)：%s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "伺服器內部錯誤", "path": request.url.path, "error": str(exc)},
    )


# ---------------- API 路由 ----------------
app.include_router(system_router, prefix=settings.api_prefix)
app.include_router(floors_router, prefix=settings.api_prefix)
app.include_router(inspections_router, prefix=settings.api_prefix)


@app.get("/", tags=["系統 System"], summary="服務資訊")
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "docs_legacy": "/api/docs",
        "health": f"{settings.api_prefix}/health",
    }


def custom_openapi() -> dict:
    """補上伺服器說明，方便 Swagger UI 呼叫。"""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {}
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.debug)