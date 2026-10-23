"""應用程式設定（由環境變數 / .env 讀取）。

環境變數優先級：實際環境變數 > .env 檔案 > 預設值
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """集中管理所有設定，避免環境變數散落各處。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 應用程式 ----------------
    app_name: str = "ROS 2 跨樓層巡檢機器人監控後台 API"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # ---------------- PostgreSQL ----------------
    postgres_user: str = "elevator"
    postgres_password: str = "elevator123"
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "elevator_monitor"
    db_auto_create: bool = False        # 正常情況由 init-db/01-init.sql 建表
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_connect_retries: int = 10        # 等待 db 容器就緒的重試次數
    db_connect_backoff: float = 2.0     # 每次重試間隔（秒）

    # ---------------- ros2-bridge ----------------
    ros_bridge_host: str = "ros2-bridge"
    ros_bridge_rest_port: int = 8080    # Bridge REST 控制埠
    ros_bridge_ws_port: int = 9090      # rosbridge_server WebSocket 埠
    ros_bridge_timeout: float = 3.0
    bridge_poll_interval: float = 5.0   # 輪詢 Bridge 取得機器人狀態的週期（秒）

    # Bridge 主動回報狀態時要呼叫的後端網址
    backend_callback_url: str = "http://web-backend:8000/api/v1/system/heartbeat"

    # ---------------- 其他 ----------------
    cors_origins: str = "*"
    heartbeat_stale_seconds: float = 30.0   # 超過此秒數視為離線

    # ---------------- 衍生屬性 ----------------
    @property
    def database_url(self) -> str:
        """SQLAlchemy 連線字串（psycopg 3 driver）。"""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def ros_bridge_base_url(self) -> str:
        """ros2-bridge REST 控制端點根網址。"""
        return f"http://{self.ros_bridge_host}:{self.ros_bridge_rest_port}"

    @property
    def ros_bridge_ws_url(self) -> str:
        """rosbridge_server WebSocket 網址（給前端使用）。"""
        return f"ws://{self.ros_bridge_host}:{self.ros_bridge_ws_port}"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """單例設定物件。"""
    return Settings()


settings = get_settings()