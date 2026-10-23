"""行级权限过滤（D-CODE3）—— 派出所数据隔离。

一、为什么需要两层机制
----------------------
只在装饰器里改「传进来的 SQL 语句」是不够的：绝大多数路由是在函数体内
`select(Agent)` 之后才执行，装饰器拿不到那条语句，隔离就成了摆设。

所以这里用两层，互补：

1. **语句级**：参数里/返回值里如果是 Select，直接追加 `dept_id = ?`；
2. **Session 级**（真正的自动兜底）：调用期间给 Session 挂
   SQLAlchemy `do_orm_execute` 事件，本函数内执行的所有 ORM SELECT
   都会自动被 `with_loader_criteria` 加上部门条件，执行完立刻卸载。
   这样即使业务同学忘了手动过滤，也漏不出去数据。

二、与业务表解耦
----------------
不绑定任何表名。只要模型上有 `dept_id` 列（可用 dept_field 换名字），
就自动纳入隔离；`model` 不传时，自动扫描所有带该列的 ORM 模型。

三、安全默认（fail-closed）
---------------------------
- 未登录 + require_auth=True  → 401，绝不返回全量
- 已登录但令牌无 dept_id      → 追加 `1=0`，查不到任何数据
- data_scope == "ALL"        → 不加过滤（分局管理员看全量）

四、用法
--------
    @router.get("/agents")
    @filter_by_dept(model=Agent)          # 也可以省略 model
    def list_agents(db: Session = Depends(get_db), user=Depends(get_current_user)):
        return db.execute(select(Agent).where(Agent.is_deleted == 0)).scalars().all()

    # 手动方式（脚本、后台任务里用）
    stmt = apply_dept_filter(select(Agent), dept_id=8, model=Agent)
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import Select, event, false
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.context import get_current_user_ctx

logger = logging.getLogger(__name__)


class DeptScopeError(Exception):
    """权限过滤无法安全执行时抛出（未登录、模型缺隔离字段等）。"""

    def __init__(self, detail: str = "无权访问该数据", status_code: int = 403):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


# ---------------------------------------------------------------------------
# 作用域解析
# ---------------------------------------------------------------------------
def _resolve_scope(
    explicit_dept_id: int | None,
    respect_data_scope: bool,
    require_auth: bool,
) -> tuple[int | None, bool]:
    """计算本次查询要过滤的 dept_id。

    Returns:
        (dept_id, unrestricted)
        unrestricted=True 表示不加任何条件（全局管理员 / 显式放行）。
    """
    if explicit_dept_id is not None:  # 显式指定优先（测试、离线任务）
        return int(explicit_dept_id), False

    user = get_current_user_ctx()
    if user is None or not user.is_authenticated:
        if require_auth:
            raise DeptScopeError("未登录或登录已失效", status_code=401)
        return None, True

    if respect_data_scope and user.is_global_scope:
        return None, True  # 分局管理员，可见全量

    return user.dept_id, False


# ---------------------------------------------------------------------------
# 语句级过滤
# ---------------------------------------------------------------------------
def _infer_entity(stmt: Select) -> Any:
    """从 Select 语句推断主实体（未显式传 model 时使用）。"""
    try:
        for desc in stmt.column_descriptions:
            entity = desc.get("entity")
            if entity is not None:
                return entity
    except Exception:  # pragma: no cover
        pass
    return None


def apply_dept_filter(
    stmt: Select,
    dept_id: int | None,
    model: Any = None,
    dept_field: str = "dept_id",
) -> Select:
    """给 Select 语句追加部门隔离条件。

    Args:
        stmt: 原始查询语句。
        dept_id: 当前用户部门 ID；None 时追加 1=0（宁可查不到，不可漏数据）。
        model: 业务模型类；不传则从语句自动推断。
        dept_field: 隔离字段名，默认 dept_id。

    Raises:
        DeptScopeError: 模型上找不到隔离字段（配置错误，必须暴露而不是放行）。
    """
    entity = model or _infer_entity(stmt)
    if entity is None:
        raise DeptScopeError("无法确定要过滤的数据表，请显式传 model 参数")

    column = getattr(entity, dept_field, None)
    if column is None:
        raise DeptScopeError(
            f"模型 {getattr(entity, '__name__', entity)} 缺少 {dept_field} 列，无法做行级隔离"
        )

    if dept_id is None:
        logger.warning("权限过滤缺少 dept_id，已降级为 1=0：model=%s", entity)
        return stmt.where(false())

    return stmt.where(column == int(dept_id))


def _filter_args(
    args: tuple, kwargs: dict, dept_id: int, model: Any, dept_field: str
) -> tuple[tuple, dict]:
    """把参数里已有的 Select 语句替换为过滤后的版本。"""
    new_args = list(args)
    args_changed = False
    for idx, value in enumerate(new_args):
        if isinstance(value, Select):
            new_args[idx] = apply_dept_filter(value, dept_id, model, dept_field)
            args_changed = True

    new_kwargs = dict(kwargs)
    for key, value in kwargs.items():
        if isinstance(value, Select):
            new_kwargs[key] = apply_dept_filter(value, dept_id, model, dept_field)

    return (tuple(new_args) if args_changed else args), new_kwargs


def _filter_result(result: Any, dept_id: int, model: Any, dept_field: str) -> Any:
    """函数返回 Select（延迟执行风格）时，返回前补上过滤条件。"""
    if isinstance(result, Select):
        return apply_dept_filter(result, dept_id, model, dept_field)
    return result


# ---------------------------------------------------------------------------
# Session 级自动过滤
# ---------------------------------------------------------------------------
def _collect_scoped_models(model: Any, dept_field: str) -> list[Any]:
    """收集需要隔离的模型：指定了就用指定的，否则扫描全部带隔离字段的模型。"""
    if model is not None:
        return [model]

    import app.models  # noqa: F401  确保所有模型已注册到 mapper 表
    from app.db.base import Base

    result = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, dept_field):
            result.append(cls)
    return result


def _install_session_scope(
    session: Session, dept_id: int, model: Any, dept_field: str
) -> Callable | None:
    """给 Session 挂临时过滤器，返回 listener 以便卸载。

    原理：监听 `do_orm_execute`，在每条 ORM SELECT 执行前叠加
    `with_loader_criteria`。它对主查询、子查询、aliased 实体都生效。
    """
    models = _collect_scoped_models(model, dept_field)
    if not models:
        return None

    def _listener(orm_execute_state: Any) -> None:
        # 只处理真正的 SELECT；跳过列加载/关系加载，避免刷新对象时误伤
        if not orm_execute_state.is_select:
            return
        if orm_execute_state.is_column_load or orm_execute_state.is_relationship_load:
            return

        stmt = orm_execute_state.statement
        for entity in models:
            column = getattr(entity, dept_field)
            # 这里用「SQL 表达式」而不是 lambda：lambda 里的自由变量会被
            # SQLAlchemy 的 lambda 追踪器包装，导致 getattr(cls, "dept_id") 报错。
            stmt = stmt.options(
                with_loader_criteria(entity, column == int(dept_id), include_aliases=False)
            )
        orm_execute_state.statement = stmt

    event.listen(session, "do_orm_execute", _listener)
    return _listener


def _uninstall_session_scope(session: Session, listener: Callable | None) -> None:
    if listener is None:
        return
    try:
        event.remove(session, "do_orm_execute", listener)
    except Exception:  # pragma: no cover
        logger.warning("卸载 Session 权限过滤器失败", exc_info=True)


def _find_session(args: tuple, kwargs: dict) -> Session | None:
    """从函数参数里找出 Session（FastAPI 依赖注入后就是实例）。"""
    for value in list(kwargs.values()) + list(args):
        if isinstance(value, Session):
            return value
    return None


# ---------------------------------------------------------------------------
# 装饰器
# ---------------------------------------------------------------------------
def filter_by_dept(
    _func: Callable | None = None,
    *,
    model: Any = None,
    dept_field: str = "dept_id",
    respect_data_scope: bool = True,
    require_auth: bool = True,
    dept_id_param: str = "_dept_id",
    session_scope: bool = True,
) -> Callable:
    """自动按派出所隔离数据的装饰器。

    Args:
        model: 业务模型类；不传自动识别所有带 dept_id 的表。
        dept_field: 隔离字段名，个别表叫 org_id 时可改。
        respect_data_scope: 是否让 data_scope=ALL 的管理员看全量。
        require_auth: 未登录是否直接 401。公共接口可设 False。
        dept_id_param: 允许 `_dept_id=5` 覆盖部门（测试/定时任务用）。
        session_scope: 是否启用 Session 级自动过滤（默认开）。
    """

    def decorator(func: Callable) -> Callable:
        def _prepare(kwargs: dict) -> tuple[int | None, bool]:
            return _resolve_scope(
                kwargs.pop(dept_id_param, None), respect_data_scope, require_auth
            )

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                dept_id, unrestricted = _prepare(kwargs)
                if unrestricted or dept_id is None:
                    return await func(*args, **kwargs)

                args, kwargs = _filter_args(args, kwargs, dept_id, model, dept_field)
                session = _find_session(args, kwargs) if session_scope else None
                listener = (
                    _install_session_scope(session, dept_id, model, dept_field)
                    if session is not None
                    else None
                )
                try:
                    result = await func(*args, **kwargs)
                finally:
                    _uninstall_session_scope(session, listener)
                return _filter_result(result, dept_id, model, dept_field)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            dept_id, unrestricted = _prepare(kwargs)
            if unrestricted or dept_id is None:
                return func(*args, **kwargs)

            args, kwargs = _filter_args(args, kwargs, dept_id, model, dept_field)
            session = _find_session(args, kwargs) if session_scope else None
            listener = (
                _install_session_scope(session, dept_id, model, dept_field)
                if session is not None
                else None
            )
            try:
                result = func(*args, **kwargs)
            finally:
                _uninstall_session_scope(session, listener)
            return _filter_result(result, dept_id, model, dept_field)

        return sync_wrapper

    if _func is not None:  # @filter_by_dept 无参写法
        return decorator(_func)
    return decorator


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------
def with_dept_scope(stmt: Select, model: Any = None, dept_field: str = "dept_id") -> Select:
    """从上下文取当前用户部门，直接给语句加条件。"""
    dept_id, unrestricted = _resolve_scope(None, True, True)
    if unrestricted:
        return stmt
    return apply_dept_filter(stmt, dept_id, model, dept_field)


def ensure_dept_access(obj_dept_id: int | None) -> None:
    """单对象越权校验：详情 / 修改 / 删除前调用。

    Raises:
        DeptScopeError: 401 未登录 / 403 越权访问其他派出所数据。
    """
    user = get_current_user_ctx()
    if user is None or not user.is_authenticated:
        raise DeptScopeError("未登录或登录已失效", status_code=401)
    if user.is_global_scope:
        return
    if obj_dept_id is None or int(obj_dept_id) != int(user.dept_id or -1):
        raise DeptScopeError("无权访问其他派出所的数据")
