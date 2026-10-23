"""应用入口。

启动：
    uvicorn app.main:app --reload --port 8000
接口文档：
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.middleware import AuthContextMiddleware
from app.routers import api_router
from app.utils.permission import DeptScopeError

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="民警工作台后端 —— 基础数据、权限、审计、网关安全基础层",
)

# 鉴权中间件（放在最外层，先于业务逻辑执行）
app.add_middleware(
    AuthContextMiddleware,
    whitelist=settings.whitelist_paths,
    strict=settings.auth_strict,
)

# 跨域：允许前端联调；上线时把 allow_origins 收紧到具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DeptScopeError)
async def dept_scope_error_handler(request: Request, exc: DeptScopeError) -> JSONResponse:
    """把越权/未登录异常统一转成 JSON 响应。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": "DEPT_SCOPE_DENIED"},
    )


@app.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    """探活接口，白名单放行，不需要令牌。"""
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version}


@app.get("/api/v1/me", tags=["系统"], summary="当前登录人信息")
def who_am_i(request: Request) -> dict:
    """返回令牌里的身份信息，用来验证鉴权链路是否打通。"""
    from app.core.context import get_current_user_ctx

    user = get_current_user_ctx()
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user_id": user.user_id,
        "police_no": user.police_no,
        "dept_id": user.dept_id,
        "roles": user.roles,
        "data_scope": user.data_scope,
    }


app.include_router(api_router)
