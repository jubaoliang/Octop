"""SQLAlchemy 声明基类与公共列。

这里的字段规范与 `sql/01_base_tables.sql` 严格一一对应，改一处必须同步另一处。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# PostgreSQL 用 BIGSERIAL，本地 SQLite 测试需要 INTEGER 才能自增，
# with_variant 让同一份模型在两种库上都能跑。
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


class PKMixin:
    """主键规范：全局统一 id，BIGSERIAL 自增。"""

    id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True, comment="主键ID"
    )


class TimestampMixin:
    """时间字段规范：创建时间、更新时间由数据库与应用层双重兜底。"""

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class SoftDeleteMixin:
    """软删除规范：0 正常，1 已删除；查询时记得过滤。"""

    is_deleted: Mapped[int] = mapped_column(
        SmallInteger,
        default=0,
        server_default="0",
        nullable=False,
        comment="软删除标记：0正常 1已删除",
    )
