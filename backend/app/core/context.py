"""请求级上下文：把「当前登录用户」放在 ContextVar 里。

为什么用 ContextVar 而不是全局变量：
- 每个请求有独立上下文，天然线程/协程安全；
- 权限装饰器（@filter_by_dept）不需要从函数参数里"猜" dept_id，
  直接读上下文即可，真正做到与业务表解耦。

写入点在鉴权中间件（app/core/middleware.py），它在 ASGI 层、
与路由处于同一条上下文链上，因此下游依赖和路由都能读到。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(slots=True)
class CurrentUser:
    """当前登录用户（来自 JWT，不查库）。"""

    user_id: int | None = None
    police_no: str | None = None
    dept_id: int | None = None
    roles: list[str] = field(default_factory=list)
    data_scope: str = "DEPT"
    raw: dict = field(default_factory=dict)

    @property
    def is_authenticated(self) -> bool:
        """是否已通过鉴权。"""
        return self.user_id is not None

    @property
    def is_global_scope(self) -> bool:
        """是否拥有全局数据范围（分局管理员/超级管理员）。"""
        return self.data_scope.upper() == "ALL"

    def has_role(self, *role_codes: str) -> bool:
        """判断是否拥有指定角色之一。"""
        return bool(set(self.roles) & set(role_codes))


_current_user: ContextVar[CurrentUser | None] = ContextVar(
    "current_user", default=None
)


def set_current_user(user: CurrentUser | None) -> Token:
    """写入当前用户，返回可用于还原的 token。"""
    return _current_user.set(user)


def reset_current_user(token: Token) -> None:
    """还原到写入前的上下文（中间件 finally 中调用）。"""
    _current_user.reset(token)


def get_current_user_ctx() -> CurrentUser | None:
    """读取当前用户，未鉴权时返回 None。"""
    return _current_user.get()


def get_current_dept_id() -> int | None:
    """读取当前用户的派出所 ID，供权限过滤使用。"""
    user = _current_user.get()
    return user.dept_id if user else None


def build_current_user(payload: dict) -> CurrentUser:
    """把 JWT payload 转成 CurrentUser。

    中间件和依赖层共用这一份转换逻辑，避免两处字段解析不一致。
    """
    roles = payload.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    return CurrentUser(
        user_id=payload.get("sub"),
        police_no=payload.get("police_no"),
        dept_id=payload.get("dept_id"),
        roles=list(roles),
        data_scope=(payload.get("data_scope") or "DEPT").upper(),
        raw=payload,
    )
