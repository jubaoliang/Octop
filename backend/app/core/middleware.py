"""鉴权中间件（网关层，D-CODE5 的拦截部分）。

为什么用纯 ASGI 中间件而不是 BaseHTTPMiddleware：
BaseHTTPMiddleware 会额外包一层 task，ContextVar 的传播在部分版本里不可靠；
纯 ASGI 中间件和路由在同一条上下文链上，set 之后下游一定能读到。

职责边界：
- 白名单路径 → 直接放行（登录、健康检查、文档）
- 白名单外 → 校验 JWT，失败直接返回 401（不进入路由）
- 校验通过 → 把用户写进 ContextVar，供依赖和权限装饰器使用
"""

from __future__ import annotations

import logging

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import settings
from app.core.context import build_current_user, reset_current_user, set_current_user
from app.core.security import TokenError, decode_access_token, parse_bearer_token
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def is_whitelisted(path: str, whitelist: tuple[str, ...] | list[str]) -> bool:
    """判断路径是否免鉴权。

    规则：
    - 完全相等 → 命中
    - 白名单项以 "/" 结尾 → 前缀匹配（如 /static/）
    - 白名单项含 "*" → 通配（如 /api/public/*）
    """
    for item in whitelist:
        if not item:
            continue
        if item == path:
            return True
        if item.endswith("/") and path.startswith(item):
            return True
        if "*" in item:
            prefix, _, suffix = item.partition("*")
            if path.startswith(prefix) and (not suffix or path.endswith(suffix)):
                return True
    return False


def _extract_token_from_scope(scope: Scope) -> str | None:
    """从 ASGI scope 的 headers 里取 Bearer token。"""
    for key, value in scope.get("headers") or []:
        if key == b"authorization":
            return parse_bearer_token(value.decode("latin-1"))
    return None


def _unauthorized_response(detail: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail, "code": code},
        headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": code},
    )


class AuthContextMiddleware:
    """JWT 鉴权 + 用户上下文注入。

    Args:
        app: 下游 ASGI 应用。
        whitelist: 免鉴权路径，默认取配置。
        strict: True 时白名单外无有效令牌直接 401。
    """

    def __init__(
        self,
        app: ASGIApp,
        whitelist: tuple[str, ...] | list[str] | None = None,
        strict: bool | None = None,
    ) -> None:
        self.app = app
        self.whitelist = tuple(whitelist if whitelist is not None else settings.whitelist_paths)
        self.strict = settings.auth_strict if strict is None else strict

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 只处理 HTTP 请求，WebSocket / lifespan 直接透传
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/") or "/"
        if scope.get("method") == "OPTIONS" or is_whitelisted(path, self.whitelist):
            # 预检请求与白名单放行
            await self.app(scope, receive, send)
            return

        token = _extract_token_from_scope(scope)
        if not token:
            if self.strict:
                await _unauthorized_response("缺少身份令牌，请先登录", "TOKEN_MISSING")(
                    scope, receive, send
                )
                return
            await self.app(scope, receive, send)
            return

        try:
            payload = decode_access_token(token)
        except TokenError as exc:
            logger.info("令牌校验失败: path=%s code=%s", path, exc.error_code)
            if self.strict:
                await _unauthorized_response(exc.detail, exc.error_code)(
                    scope, receive, send
                )
                return
            await self.app(scope, receive, send)
            return

        # 解析成功 → 注入上下文，下游依赖与权限装饰器直接读
        ctx_token = set_current_user(build_current_user(payload))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_current_user(ctx_token)
