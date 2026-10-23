"""ORM 模型统一出口，方便 `from app.models import Agent` 这样导入。"""

from app.models.biz import Agent, AgentVersion, AuditTask, KbChunk, KbDoc, Template
from app.models.system import (
    Dept,
    Message,
    OperationLog,
    Role,
    RolePerm,
    UserPolice,
    UserRole,
)

__all__ = [
    # 基础/权限相关
    "Dept",
    "UserPolice",
    "Role",
    "UserRole",
    "RolePerm",
    "OperationLog",
    "Message",
    # 业务相关（字段待 B 最终确认）
    "Agent",
    "AgentVersion",
    "Template",
    "AuditTask",
    "KbDoc",
    "KbChunk",
]
