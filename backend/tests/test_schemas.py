"""Pydantic Schema 测试（D-CODE6 验收）。

重点验证三件事：
1. Out 模型能从 ORM 对象直接序列化（from_attributes）；
2. 敏感字段在出参里自动脱敏，不会裸奔；
3. 入参模型拒绝未定义字段（extra=forbid），防止前端塞 dept_id 越权。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.system import Dept as DeptORM
from app.models.system import UserPolice as UserORM
from app.schemas.biz import AgentCreate, TemplateCreate
from app.schemas.system import (
    DeptCreate,
    DeptOut,
    MessageOut,
    OperationLogOut,
    RoleCreate,
    UserPoliceCreate,
    UserPoliceOut,
)


class TestFromORM:
    """Out 模型 ← ORM 对象（用真实入库后的对象，server_default 才有值）。"""

    def test_user_out_masks_sensitive_fields(self, db_session, seed):
        orm = seed["users"]["police_a"]  # 已入库，phone / id_card 都有值
        out = UserPoliceOut.model_validate(orm)
        # 注意：脱敏发生在**序列化**阶段（field_serializer），
        # 也就是 FastAPI 返回响应时那一层，所以断言要看 model_dump 的结果。
        data = out.model_dump()

        assert data["police_no"] == "060101"
        assert data["phone"] == "138****0002"          # 已脱敏
        assert data["id_card"] == "110101********1234"
        # 关键：绝不能带出密码哈希
        assert "password_hash" not in data

    def test_dept_out(self, db_session, seed):
        dept = seed["dept_a"]
        dept.leader_phone = "13800001111"
        db_session.commit()

        out = DeptOut.model_validate(dept)
        data = out.model_dump()
        assert data["dept_name"] == "A派出所"
        assert data["leader_phone"] == "138****1111"
        assert data["is_deleted"] == 0

    def test_message_out(self):
        from datetime import datetime

        class FakeMessage:
            id = 9
            title = "审核结果"
            content = "已通过"
            msg_type = "AUDIT"
            biz_type = "audit_task"
            biz_id = 12
            sender_id = None
            receiver_id = 5
            receiver_dept_id = 2
            is_read = 0
            read_time = None
            create_time = datetime(2026, 10, 22, 10, 0, 0)
            update_time = datetime(2026, 10, 22, 10, 0, 0)

        out = MessageOut.model_validate(FakeMessage())
        assert out.title == "审核结果"
        assert out.is_read == 0

    def test_operation_log_out(self):
        from datetime import datetime

        class FakeLog:
            id = 1
            user_id = 2
            police_no = "060101"
            dept_id = 3
            op_type = "CREATE"
            target_type = "agent"
            target_id = 8
            detail = '{"a": 1}'
            client_ip = "10.0.0.1"
            is_sensitive = 1
            create_time = datetime(2026, 10, 22, 11, 0, 0)

        out = OperationLogOut.model_validate(FakeLog())
        assert out.op_type == "CREATE"
        assert out.is_sensitive == 1


class TestInputValidation:
    """入参校验。"""

    def test_user_create_requires_password(self):
        with pytest.raises(ValidationError):
            UserPoliceCreate(police_no="060101", real_name="张三", dept_id=1)

    def test_user_create_password_too_short(self):
        with pytest.raises(ValidationError):
            UserPoliceCreate(
                police_no="060101", real_name="张三", dept_id=1, password="123"
            )

    def test_police_no_rejects_symbols(self):
        with pytest.raises(ValidationError):
            UserPoliceCreate(
                police_no="06@101", real_name="张三", dept_id=1, password="Test@12345"
            )

    def test_role_data_scope_whitelist(self):
        assert RoleCreate(role_code="police", role_name="民警", data_scope="dept").data_scope == "DEPT"
        with pytest.raises(ValidationError):
            RoleCreate(role_code="x", role_name="x", data_scope="GLOBAL")

    def test_dept_create_ok(self):
        d = DeptCreate(dept_name="东城派出所", dept_code="PCS001")
        assert d.dept_level == 3 and d.status == 1

    def test_agent_create_forbids_extra_field(self):
        """前端多传 dept_id 必须被拒绝 —— 防越权写入的第一道闸。"""
        with pytest.raises(ValidationError):
            AgentCreate(agent_code="A-1", agent_name="x", dept_id=99)

    def test_agent_code_charset(self):
        assert AgentCreate(agent_code="A-1_b", agent_name="x").agent_code == "A-1_b"
        with pytest.raises(ValidationError):
            AgentCreate(agent_code="A 1", agent_name="x")

    def test_template_create(self):
        with pytest.raises(ValidationError):
            TemplateCreate(template_code="T", template_name="")  # 名称不能为空
