"""PostgreSQL 連線設定（SQLAlchemy 2.0 + psycopg 3）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

logger = logging.getLogger(__name__)

# pool_pre_ping：避免資料庫重啟後取得失效連線
engine: Engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=1800,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依賴注入：每個請求一個 Session。"""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def wait_for_database(max_retries: int | None = None, backoff: float | None = None) -> None:
    """等待 db 容器完成初始化（docker-compose 啟動順序不一定保證）。"""
    retries = settings.db_connect_retries if max_retries is None else max_retries
    delay = settings.db_connect_backoff if backoff is None else backoff

    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("資料庫連線成功：%s:%s/%s",
                        settings.postgres_host, settings.postgres_port, settings.postgres_db)
            return
        except OperationalError as exc:
            if attempt >= retries:
                logger.error("資料庫連線失敗（已重試 %s 次）：%s", attempts := attempt, exc)
                raise
            logger.warning("資料庫尚未就緒（%s/%s），%.1f 秒後重試…", attempt, retries, delay)
            time.sleep(delay)


def create_tables_if_needed() -> None:
    """僅在 DB_AUTO_CREATE=true 時建立資料表（開發環境便利用）。"""
    if not settings.db_auto_create:
        logger.info("略過自動建表（DB_AUTO_CREATE=false），資料表由 init-db/01-init.sql 建立")
        return

    from .models import Base  # 避免循環匯入

    Base.metadata.create_all(bind=engine)
    logger.info("已依 ORM 模型自動建立資料表")


def check_database() -> bool:
    """健康檢查用。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("資料庫健康檢查失敗：%s", exc)
        return False