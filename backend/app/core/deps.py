"""FastAPI 依赖项：当前登录用户（D-CODE5）、角色校验。

get_current_user 的取值顺序：
1. 上下文里已有（鉴权中间件在网关层解析过）—— 正常链路走这里，零重复解析
2. 从 Authorization 头现场解析 —— 兜底（比如中间件被关掉的单元测试）
3. 都拿不到 → 401

令牌过期 / 非法 / 缺字段，一律 401，且响应头带 WWW-Authenticate: Bearer。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.context import (
    CurrentUser,
    build_current_user,
    get_current_user_ctx,
    set_current_user,
)
from app.core.security import TokenError, decode_access_token, parse_bearer_token

# auto_error=False：自己抛 401，保证错误体格式统一
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="PoliceBearer",
    description="登录接口返回的 access_token，格式：Bearer <token>",
)


def _unauthorized(detail: str, code: str = "TOKEN_INVALID") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer", "X-Auth-Error": code},
    )


def _extract_token(
    request: Request, credentials: HTTPAuthorizationCredentials | None
) -> str | None:
    if credentials and credentials.credentials:
        return credentials.credentials
    # 兜底：某些网关会改写头名，这里再直接读一次原始头
    return parse_bearer_token(request.headers.get("authorization"))


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """依赖项：解析并返回当前登录用户，不通过则 401。

    业务路由用法：

        @router.get("/me")
        def me(user: CurrentUser = Depends(get_current_user)):
            return {"police_no": user.police_no, "dept_id": user.dept_id}
    """
    # 1) 中间件已解析（推荐路径）
    ctx_user = get_current_user_ctx()
    if ctx_user is not None and ctx_user.is_authenticated:
        return ctx_user

    # 2) 现场解析
    token = _extract_token(request, credentials)
    if not token:
        raise _unauthorized("缺少身份令牌，请先登录", "TOKEN_MISSING")

    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise _unauthorized(exc.detail, exc.error_code) from exc

    user = build_current_user(payload)
    if user.dept_id is None and not user.is_global_scope:
        # 令牌里没有派出所归属，行级隔离无法生效，直接拒绝
        raise _unauthorized("令牌缺少部门信息，请重新登录", "TOKEN_NO_DEPT")

    set_current_user(user)  # 兜底写回上下文，供 @filter_by_dept 使用
    return user


def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser | None:
    """允许匿名的版本：拿不到有效用户时返回 None，不抛 401。

    用于「登录也返回数据、未登录返回阉割版」的接口。
    """
    ctx_user = get_current_user_ctx()
    if ctx_user is not None and ctx_user.is_authenticated:
        return ctx_user

    token = _extract_token(request, credentials)
    if not token:
        return None
    try:
        return build_current_user(decode_access_token(token))
    except TokenError:
        return None


def require_roles(*role_codes: str):
    """依赖工厂：要求当前用户具备指定角色之一。

        @router.post("/agents/{id}/publish")
        def publish(user=Depends(require_roles("admin", "auditor"))):
            ...
    """
    allowed = set(role_codes)

    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(*allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要以下角色之一：{'、'.join(sorted(allowed))}",
            )
        return user

    return checker
