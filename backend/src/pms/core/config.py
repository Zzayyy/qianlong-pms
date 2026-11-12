"""应用配置：唯一来源为环境变量 / `.env`（密码不入代码）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Final
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """运行期配置。"""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_name: str = "PMS"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_secret_key: str = "please-change-me"
    log_level: str = "INFO"

    db_host: str = "192.168.1.136"
    db_port: int = 3306
    db_user: str = "qloffice"
    db_password: str = ""
    db_name: str = "qloffice"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""

    jwt_secret_key: str = "please-change-me-too"
    jwt_expire_minutes: int = 120

    upload_dir: str = Field(default="data/uploads")
    upload_max_mb: int = 20

    cors_origins: str = "http://localhost:5173"

    # 可信反向代理地址（逗号分隔，`*` 表示全部）：只有来自这些地址的请求才采信
    # `X-Forwarded-For` / `X-Real-IP`，用于审计留痕取真实客户端 IP
    trusted_proxies: str = "127.0.0.1,::1"

    @property
    def database_url(self) -> str:
        """异步 MySQL 连接串。"""
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        """Redis 连接串（密码做 URL 编码，避免 @ / & 等字符破坏解析）。"""
        auth = f":{quote(self.redis_password, safe='')}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS 白名单。"""
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取配置单例。"""
    return Settings()
