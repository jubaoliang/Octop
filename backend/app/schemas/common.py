"""Schema 公共基类与分页结构。"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """所有输出模型的基类：允许直接从 ORM 对象序列化。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ORMInput(BaseModel):
    """所有写入模型的基类：拒绝未定义字段，避免前端乱传脏数据。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PageQuery(BaseModel):
    """分页查询参数。"""

    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=200, description="每页条数")
    keyword: str | None = Field(None, max_length=100, description="模糊搜索关键词")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageResult(BaseModel, Generic[T]):
    """分页返回结构。"""

    total: int = Field(0, description="总条数")
    page: int = Field(1, description="当前页码")
    page_size: int = Field(20, description="每页条数")
    items: list[T] = Field(default_factory=list, description="数据列表")

    @classmethod
    def build(cls, total: int, items: list[T], query: PageQuery | None = None) -> "PageResult[T]":
        return cls(
            total=total,
            page=query.page if query else 1,
            page_size=query.page_size if query else len(items),
            items=items,
        )


class TimestampOut(ORMModel):
    """带时间字段的只读基类。"""

    create_time: datetime | None = Field(None, description="创建时间")
    update_time: datetime | None = Field(None, description="更新时间")
