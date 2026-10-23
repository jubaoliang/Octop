"""通用审计日志工具（D-CODE2）。

设计要点：
1. **与业务解耦**：本模块只依赖 OperationLog 模型和 SQLAlchemy Session，
   任何路由 `from app.utils.audit import write_operation_log` 即可使用。
2. **失败不阻断业务**：审计写入异常默认只记日志（raise_on_error=False），
   避免因为日志库抖动导致业务接口 500。
3. **两种调用姿势**：
   - write_operation_log(...)         —— 手工传所有字段，最灵活
   - write_operation_log_from_request(...) —— 自动从当前用户/IP 取值，最省事
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.system import OperationLog

logger = logging.getLogger(__name__)

# ---- 常用操作类型常量（避免各路由各写一套字符串） ----
OP_CREATE = "CREATE"
OP_UPDATE = "UPDATE"
OP_DELETE = "DELETE"
OP_QUERY = "QUERY"
OP_LOGIN = "LOGIN"
OP_LOGOUT = "LOGOUT"
OP_EXPORT = "EXPORT"
OP_IMPORT = "IMPORT"
OP_AUDIT = "AUDIT"          # 审核通过/驳回
OP_PUBLISH = "PUBLISH"      # 发布/上线
OP_OFFLINE = "OFFLINE"      # 下线


def get_client_ip(request: Any) -> str | None:
    """从请求中取真实客户端 IP（兼容 Nginx / 网关转发）。

    优先级：X-Forwarded-For（首个） > X-Real-IP > request.client.host
    """
    if request is None:
        return None
    try:
        headers = getattr(request, "headers", {}) or {}
        xff = headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip() or None
        xri = headers.get("x-real-ip")
        if xri:
            return xri.strip() or None
        client = getattr(request, "client", None)
        return getattr(client, "host", None)
    except Exception:  # pragma: no cover - 极端情况兜底
        return None


def _stringify_detail(detail: Any) -> str | None:
    """detail 允许传 dict / list，统一转 JSON 文本，便于后续检索。"""
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail
    try:
        return json.dumps(detail, ensure_ascii=False, default=str)
    except Exception:
        return str(detail)


def write_operation_log(
    db: Session,
    user_id: int | None = None,
    police_no: str | None = None,
    dept_id: int | None = None,
    op_type: str = "",
    target_id: int | None = None,
    detail: Any = None,
    client_ip: str | None = None,
    is_sensitive: bool | int = False,
    *,
    target_type: str | None = None,
    auto_commit: bool = True,
    raise_on_error: bool = False,
) -> OperationLog | None:
    """写入一条操作审计日志。

    Args:
        db: 数据库会话。
        user_id: 操作人用户 ID。
        police_no: 操作人警号（冗余存储，账号被删也能追责）。
        dept_id: 操作人所属部门 ID。
        op_type: 操作类型，建议用本模块 OP_* 常量。
        target_id: 操作对象 ID（如被创建的 agent.id）。
        detail: 操作详情，可传 dict 或字符串。
        client_ip: 客户端 IP。
        is_sensitive: 是否敏感操作（1 标记为敏感，审计时重点关注）。
        target_type: 操作对象类型，如 "agent"、"template"。可选补充字段。
        auto_commit: 是否立即提交。若希望和业务操作**同事务**提交，传 False。
        raise_on_error: 写入失败是否向上抛异常。默认 False（不阻断业务）。

    Returns:
        成功时返回日志对象；失败且 raise_on_error=False 时返回 None。

    Example:
        >>> write_operation_log(
        ...     db, user_id=1, police_no="060123", dept_id=10,
        ...     op_type=OP_CREATE, target_type="agent", target_id=agent.id,
        ...     detail={"agent_name": agent.agent_name}, client_ip="10.0.0.8",
        ... )
    """
    try:
        log = OperationLog(
            user_id=user_id,
            police_no=police_no,
            dept_id=dept_id,
            op_type=(op_type or "UNKNOWN").upper(),
            target_type=target_type,
            target_id=target_id,
            detail=_stringify_detail(detail),
            client_ip=client_ip,
            is_sensitive=1 if is_sensitive else 0,
            create_time=datetime.now(),
        )
        db.add(log)
        if auto_commit:
            db.commit()
            db.refresh(log)
        else:
            db.flush()
        return log
    except Exception as exc:
        if auto_commit:
            db.rollback()
        logger.exception(
            "审计日志写入失败: op_type=%s user_id=%s target=%s/%s err=%s",
            op_type, user_id, target_type, target_id, exc,
        )
        if raise_on_error:
            raise
        return None


def write_operation_log_from_request(
    db: Session,
    request: Any,
    op_type: str,
    target_id: int | None = None,
    detail: Any = None,
    is_sensitive: bool | int = False,
    *,
    target_type: str | None = None,
    auto_commit: bool = True,
) -> OperationLog | None:
    """从请求上下文自动补全操作人、IP 后写日志。

    业务路由里最常用的写法：

        write_operation_log_from_request(
            db, request, OP_CREATE, target_id=agent.id,
            target_type="agent", detail={"name": payload.agent_name},
        )
    """
    from app.core.context import get_current_user_ctx  # 延迟导入，避免循环依赖

    user = get_current_user_ctx()
    return write_operation_log(
        db,
        user_id=user.user_id if user else None,
        police_no=user.police_no if user else None,
        dept_id=user.dept_id if user else None,
        op_type=op_type,
        target_id=target_id,
        detail=detail,
        client_ip=get_client_ip(request),
        is_sensitive=is_sensitive,
        target_type=target_type,
        auto_commit=auto_commit,
    )
