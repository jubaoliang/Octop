"""全局配置：统一从环境变量 / .env 读取，前缀 PW_。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置项。

    所有字段都可以用环境变量覆盖，例如 `PW_DATABASE_URL=...`。
    """

    # ---- 基础信息 ----
    app_name: str = "民警工作台后端"
    app_version: str = "0.1.0"
    debug: bool = False

    # ---- 数据库 ----
    # PostgreSQL 示例：postgresql+psycopg://user:pwd@127.0.0.1:5432/police_workbench
    database_url: str = (
        "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/police_workbench"
    )
    sql_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ---- JWT 鉴权 ----
    jwt_secret: str = "please-change-this-secret-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    # 网关层是否严格拦截：True 时白名单外的请求没带有效 token 直接 401。
    # 联调阶段如果 B 有临时公开接口，可临时置 False（仅限开发环境）。
    auth_strict: bool = True

    # ---- 接口白名单（免鉴权），逗号分隔 ----
    # 完全相等的路径精确匹配；以 / 结尾的按前缀匹配（如 /static/）
    auth_whitelist: str = (
        "/api/auth/login,/api/auth/refresh,/health,/docs,/redoc,/openapi.json,/favicon.ico"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PW_",
        extra="ignore",
    )

    # ---- 派生属性 ----
    @property
    def whitelist_paths(self) -> tuple[str, ...]:
        """把逗号分隔的白名单字符串解析成元组。"""
        return tuple(p.strip() for p in self.auth_whitelist.split(",") if p.strip())


@lru_cache
def get_settings() -> Settings:
    """单例配置，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
