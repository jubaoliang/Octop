"""路由注册总入口。"""

from fastapi import APIRouter

from app.routers import demo_agent

api_router = APIRouter()
api_router.include_router(demo_agent.router)
