"""业务路由示例（D-CODE9）—— 给 B 参考：业务接口怎么接入权限和审计。

核心就三行：
1. `user: CurrentUser = Depends(get_current_user)`  → 拿当前登录人
2. `@filter_by_dept(model=Agent)`                   → 列表查询自动按派出所隔离
3. `write_operation_log_from_request(...)`          → 写审计日志

dept_id 一律从 user 里取，不要从请求体里取。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import CurrentUser
from app.core.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.biz import Agent
from app.schemas.biz import AgentCreate, AgentOut, AgentUpdate
from app.schemas.common import PageQuery, PageResult
from app.utils.audit import OP_CREATE, OP_QUERY, OP_UPDATE, write_operation_log_from_request
from app.utils.permission import ensure_dept_access, filter_by_dept

router = APIRouter(prefix="/api/v1/agents", tags=["示例-智能体"])


@router.get(
    "",
    response_model=PageResult[AgentOut],
    summary="查询智能体列表（自动按派出所隔离）",
)
@filter_by_dept(model=Agent)  # ← 关键：装饰器自动补 dept_id 条件
def list_agents(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """列表查询：普通民警只看本所，data_scope=ALL 的管理员看全量。

    注意 select 语句在函数内构造，装饰器会拦截返回值（Select）并追加条件。
    也可以先构造好语句再传进来，装饰器同样会处理。
    """
    stmt = select(Agent).where(Agent.is_deleted == 0)
    if keyword:
        stmt = stmt.where(Agent.agent_name.ilike(f"%{keyword}%"))

    # 统计总数（同样要隔离，所以复用同一条带过滤条件的语句）
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = (
        db.execute(stmt.order_by(Agent.id.desc()).offset((page - 1) * page_size).limit(page_size))
        .scalars()
        .all()
    )

    # 查询类日志：量大时建议只在敏感数据查询时记，这里演示写法
    write_operation_log_from_request(
        db, request, OP_QUERY, target_type="agent", detail={"keyword": keyword, "total": total}
    )
    return PageResult.build(total=total, items=rows, query=PageQuery(page=page, page_size=page_size))


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建智能体（写审计日志）",
)
def create_agent(
    request: Request,
    payload: AgentCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """创建智能体。

    要点：
    - dept_id 取 user.dept_id，绝不取 payload；
    - 先 flush 拿到自增 id，再写审计日志（target_id 才有值）；
    - 业务写入与日志写在同一个事务里，一起 commit。
    """
    exists = db.execute(
        select(Agent.id).where(Agent.agent_code == payload.agent_code, Agent.is_deleted == 0)
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "智能体编码已存在")

    agent = Agent(
        **payload.model_dump(),
        dept_id=user.dept_id,      # 服务端强制归属，防越权写入
        owner_id=user.user_id,
        status="DRAFT",
        current_version=0,
        is_deleted=0,
    )
    db.add(agent)
    db.flush()  # 拿到 agent.id

    write_operation_log_from_request(
        db,
        request,
        OP_CREATE,
        target_type="agent",
        target_id=agent.id,
        detail={"agent_code": agent.agent_code, "agent_name": agent.agent_name},
        auto_commit=False,  # 与业务同事务
    )
    db.commit()
    db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut, summary="智能体详情（单对象越权校验）")
def get_agent(
    agent_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """详情接口不用装饰器，改用 ensure_dept_access 显式校验。"""
    agent = db.get(Agent, agent_id)
    if agent is None or agent.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "智能体不存在")
    ensure_dept_access(agent.dept_id)  # ← 跨所访问直接 403
    return agent


@router.put("/{agent_id}", response_model=AgentOut, summary="修改智能体")
def update_agent(
    request: Request,
    payload: AgentUpdate,
    agent_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    agent = db.get(Agent, agent_id)
    if agent is None or agent.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "智能体不存在")
    ensure_dept_access(agent.dept_id)

    if agent.status == "PUBLISHED":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "已发布的智能体不能直接修改，请新建版本")

    changed = payload.model_dump(exclude_unset=True)
    for key, value in changed.items():
        setattr(agent, key, value)

    write_operation_log_from_request(
        db, request, OP_UPDATE, target_type="agent", target_id=agent.id,
        detail={"changed_fields": list(changed.keys())}, auto_commit=False,
    )
    db.commit()
    db.refresh(agent)
    return agent


@router.delete("/{agent_id}", summary="删除智能体（软删除，需管理员）")
def delete_agent(
    request: Request,
    agent_id: int = Path(..., gt=0),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles("admin")),  # ← 角色校验
):
    agent = db.get(Agent, agent_id)
    if agent is None or agent.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "智能体不存在")
    ensure_dept_access(agent.dept_id)

    agent.is_deleted = 1
    write_operation_log_from_request(
        db, request, "DELETE", target_type="agent", target_id=agent.id,
        detail={"agent_code": agent.agent_code}, is_sensitive=True, auto_commit=False,
    )
    db.commit()
    return {"code": 0, "message": "已删除"}
