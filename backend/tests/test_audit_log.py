"""审计日志测试（E-CODE1 · test_audit_log_write）。

覆盖两层：
1. write_operation_log 工具函数本身（字段落库、detail 序列化、敏感标记）
2. 通过接口创建智能体后，日志是否真的写进去了（业务链路联调）
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models.system import OperationLog
from app.utils.audit import (
    OP_CREATE,
    OP_QUERY,
    get_client_ip,
    write_operation_log,
    write_operation_log_from_request,
)


class TestWriteOperationLog:
    """工具函数直测。"""

    def test_basic_insert(self, db_session, seed):
        user = seed["users"]["police_a"]
        log = write_operation_log(
            db_session,
            user_id=user.id,
            police_no=user.police_no,
            dept_id=user.dept_id,
            op_type=OP_CREATE,
            target_type="agent",
            target_id=100,
            detail={"agent_name": "测试智能体"},
            client_ip="10.1.2.3",
            is_sensitive=True,
        )
        assert log is not None and log.id is not None

        row = db_session.get(OperationLog, log.id)
        assert row.user_id == user.id
        assert row.police_no == "060101"
        assert row.dept_id == user.dept_id
        assert row.op_type == "CREATE"
        assert row.target_type == "agent"
        assert row.target_id == 100
        assert row.client_ip == "10.1.2.3"
        assert row.is_sensitive == 1
        assert row.create_time is not None

    def test_detail_dict_is_json_encoded(self, db_session, seed):
        log = write_operation_log(
            db_session,
            user_id=seed["users"]["police_a"].id,
            op_type=OP_QUERY,
            detail={"keyword": "诈骗", "page": 1},
        )
        assert log is not None
        payload = json.loads(log.detail)
        assert payload["keyword"] == "诈骗"
        assert payload["page"] == 1

    def test_detail_string_kept_as_is(self, db_session, seed):
        log = write_operation_log(
            db_session,
            user_id=1,
            op_type=OP_QUERY,
            detail="导出人员名单",
        )
        assert log.detail == "导出人员名单"

    def test_op_type_uppercased(self, db_session, seed):
        log = write_operation_log(db_session, user_id=1, op_type="create")
        assert log.op_type == "CREATE"

    def test_no_commit_mode(self, db_session, seed):
        """auto_commit=False 时不提交，但与业务同事务可见。"""
        log = write_operation_log(
            db_session, user_id=1, op_type=OP_CREATE, auto_commit=False
        )
        assert log is not None and log.id is not None
        assert db_session.execute(select(OperationLog)).scalars().all()

    def test_get_client_ip_priority(self):
        class FakeRequest:
            def __init__(self, headers, host="127.0.0.1"):
                self.headers = headers
                self.client = type("C", (), {"host": host})()

        assert get_client_ip(FakeRequest({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})) == "1.1.1.1"
        assert get_client_ip(FakeRequest({"x-real-ip": "3.3.3.3"})) == "3.3.3.3"
        assert get_client_ip(FakeRequest({})) == "127.0.0.1"
        assert get_client_ip(None) is None


class TestAuditThroughApi:
    """接口链路：创建智能体后必须留痕。"""

    def test_create_agent_writes_log(self, client, headers, seed, db_session):
        resp = client.post(
            "/api/v1/agents",
            json={"agent_code": "A-LOG-1", "agent_name": "留痕测试"},
            headers=headers["police_a"],
        )
        assert resp.status_code == 201
        agent_id = resp.json()["id"]

        rows = (
            db_session.execute(
                select(OperationLog).where(
                    OperationLog.target_type == "agent",
                    OperationLog.target_id == agent_id,
                    OperationLog.op_type == "CREATE",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        log = rows[0]
        assert log.police_no == "060101"
        assert log.dept_id == seed["dept_a"].id
        assert "A-LOG-1" in (log.detail or "")

    def test_list_writes_query_log(self, client, headers, seed, db_session):
        client.get("/api/v1/agents", headers=headers["police_a"])
        rows = (
            db_session.execute(select(OperationLog).where(OperationLog.op_type == "QUERY"))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    def test_delete_marks_sensitive(self, client, headers, seed, db_session):
        created = client.post(
            "/api/v1/agents",
            json={"agent_code": "A-LOG-2", "agent_name": "删除留痕"},
            headers=headers["police_a"],
        ).json()

        resp = client.delete(f"/api/v1/agents/{created['id']}", headers=headers["admin"])
        assert resp.status_code == 200

        log = db_session.execute(
            select(OperationLog).where(
                OperationLog.target_id == created["id"],
                OperationLog.op_type == "DELETE",
            )
        ).scalar_one()
        assert log.is_sensitive == 1
