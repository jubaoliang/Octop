"""pytest 测试脚手架（E-CODE1）—— 权限、审计日志、脱敏、数据隔离。

提供的 fixture
--------------
engine      每次用例一个干净的 SQLite 内存库（表结构由 ORM 模型自动创建）
db_session  数据库会话
seed        预置数据：2 个派出所 + 3 个角色 + 3 个警员（管理员/普通民警/审核员）
client      带依赖覆盖的 FastAPI TestClient
tokens      三种角色对应的真实 JWT（走的是正式签发逻辑，不是假数据）
headers     {role: {"Authorization": "Bearer xxx"}}

为什么测试不连 PostgreSQL：
单元测试要快、要能离线跑。SQLite 内存库足够验证权限逻辑，
真实 PG 的语法兼容性交给 99_isolation_check.sql 在联调环境验证。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# 环境必须在 import app.* 之前设置：让 session.py 建的 engine 指向 SQLite，
# 避免测试环境去连生产 PostgreSQL。
# ---------------------------------------------------------------------------
os.environ.setdefault("PW_DATABASE_URL", "sqlite://")
os.environ.setdefault("PW_AUTH_STRICT", "true")
os.environ.setdefault("PW_JWT_SECRET", "test-only-secret-key-at-least-32-bytes-long")
os.environ.setdefault("PW_ACCESS_TOKEN_EXPIRE_MINUTES", "60")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  确保所有模型注册到 metadata
from app.core.security import create_access_token  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.system import Dept, Role, UserPolice, UserRole  # noqa: E402


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
@pytest.fixture()
def engine():
    """每个用例一个全新的内存库，用例之间零污染。"""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """数据库会话。"""
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session: Session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# 预置数据
# ---------------------------------------------------------------------------
@pytest.fixture()
def seed(db_session: Session) -> dict:
    """两个派出所 + 三个角色 + 三个警员。

    - dept_a / dept_b：用于验证跨所隔离
    - admin：data_scope=ALL，可看全量
    - police_a / police_b：普通民警，data_scope=DEPT
    - auditor_a：审核员，属于 A 所
    """
    dept_a = Dept(dept_name="A派出所", dept_code="A001", dept_level=3, status=1, is_deleted=0)
    dept_b = Dept(dept_name="B派出所", dept_code="B001", dept_level=3, status=1, is_deleted=0)
    db_session.add_all([dept_a, dept_b])
    db_session.flush()

    role_admin = Role(role_code="admin", role_name="系统管理员", data_scope="ALL", status=1, is_deleted=0)
    role_police = Role(role_code="police", role_name="普通民警", data_scope="DEPT", status=1, is_deleted=0)
    role_auditor = Role(role_code="auditor", role_name="审核员", data_scope="DEPT", status=1, is_deleted=0)
    db_session.add_all([role_admin, role_police, role_auditor])
    db_session.flush()

    def _mk_user(police_no: str, real_name: str, dept: Dept, role: Role, phone: str) -> UserPolice:
        user = UserPolice(
            police_no=police_no,
            real_name=real_name,
            password_hash="$2b$12$test.hash.not.real",  # 测试不校验密码
            dept_id=dept.id,
            phone=phone,
            id_card="110101199003071234",
            gender=1,
            status=1,
            is_deleted=0,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(UserRole(user_id=user.id, role_id=role.id, create_time=datetime.now()))
        return user

    admin = _mk_user("000001", "分局管理员", dept_a, role_admin, "13800000001")
    police_a = _mk_user("060101", "A所民警", dept_a, role_police, "13800000002")
    police_b = _mk_user("060201", "B所民警", dept_b, role_police, "13800000003")
    auditor_a = _mk_user("060102", "A所审核员", dept_a, role_auditor, "13800000004")
    db_session.commit()

    return {
        "dept_a": dept_a,
        "dept_b": dept_b,
        "roles": {"admin": role_admin, "police": role_police, "auditor": role_auditor},
        "users": {
            "admin": admin,
            "police_a": police_a,
            "police_b": police_b,
            "auditor_a": auditor_a,
        },
    }


# ---------------------------------------------------------------------------
# 令牌
# ---------------------------------------------------------------------------
@pytest.fixture()
def tokens(seed: dict) -> dict[str, str]:
    """按角色签发真实 JWT（用的就是生产同一套 create_access_token）。"""

    def _issue(user: UserPolice, role_code: str, data_scope: str) -> str:
        return create_access_token(
            user.id,
            police_no=user.police_no,
            dept_id=user.dept_id,
            roles=[role_code],
            data_scope=data_scope,
        )

    users = seed["users"]
    return {
        "admin": _issue(users["admin"], "admin", "ALL"),
        "police_a": _issue(users["police_a"], "police", "DEPT"),
        "police_b": _issue(users["police_b"], "police", "DEPT"),
        "auditor_a": _issue(users["auditor_a"], "auditor", "DEPT"),
    }


@pytest.fixture()
def headers(tokens: dict[str, str]) -> dict[str, dict[str, str]]:
    """{角色: 请求头}，直接 client.get(..., headers=headers["police_a"])。"""
    return {k: {"Authorization": f"Bearer {v}"} for k, v in tokens.items()}


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(db_session: Session):
    """被测应用的 TestClient，数据库依赖替换成测试会话。"""

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
