"""数据库连接与会话管理。

- 生产：PostgreSQL（psycopg3 驱动）
- 测试：SQLite（内存库），通过 create_engine_for 复用同一套会话配置
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def create_engine_for(url: str) -> Engine:
    """按 DSN 创建 Engine，自动适配 SQLite（无连接池参数）与 PostgreSQL。"""
    common = dict(echo=settings.sql_echo, pool_pre_ping=True, future=True)
    if url.startswith("sqlite"):
        # SQLite 不支持 pool_size / max_overflow
        return create_engine(url, **common)
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=1800,  # 半小时回收，避免被防火墙掐断的空闲连接
        **common,
    )


engine: Engine = create_engine_for(settings.database_url)

# expire_on_commit=False：commit 后对象依然可读，方便直接序列化返回
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def get_db():
    """FastAPI 依赖：每个请求一个 Session，请求结束自动关闭。"""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
