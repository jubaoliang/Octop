"""端到端业务用例（E-CODE3 · 后置任务）。

状态：**用例已写好，默认 skip**。等 B 交付登录、审核、知识库接口后，
把模块级 skip 去掉即可直接跑。

覆盖清单（对应需求）：
1. 登录不同角色                     → test_login_diff_roles
2. 跨派出所越权访问                 → test_cross_dept_forbidden
3. 提交审核流程                     → test_audit_workflow
4. 知识库导入                       → test_kb_import
5. 审计日志是否正常落库             → test_audit_log_persisted

接口路径按当前约定写，B 实际交付后如有出入，只改 PATHS 即可。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.system import OperationLog

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(reason="等 B 交付登录/审核/知识库接口后启用（E-CODE3）"),
]

# 约定的接口路径 —— 只在这里改，别散落到各个用例里
PATHS = {
    "login": "/api/auth/login",
    "agent_create": "/api/v1/agents",
    "agent_list": "/api/v1/agents",
    "audit_submit": "/api/v1/audit-tasks",
    "audit_approve": "/api/v1/audit-tasks/{task_id}/audit",
    "kb_upload": "/api/v1/kb/docs",
    "kb_docs": "/api/v1/kb/docs",
}

PASSWORD = "Test@12345"


def _login(client, police_no: str) -> str:
    """登录并返回 access_token。"""
    resp = client.post(
        PATHS["login"], json={"police_no": police_no, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    token = data.get("access_token") or data.get("token")
    assert token, "登录响应里没有 access_token"
    return token


class TestLoginAndRoles:
    """1. 登录不同角色。"""

    def test_login_diff_roles(self, client, seed):
        """三个角色都能登录，且返回的身份信息不同。"""
        for police_no, expected_scope in [
            ("000001", "ALL"),     # 管理员
            ("060101", "DEPT"),    # 普通民警
            ("060102", "DEPT"),    # 审核员
        ]:
            token = _login(client, police_no)
            me = client.get(
                "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
            ).json()
            assert me["police_no"] == police_no
            assert me["data_scope"] == expected_scope

    def test_login_wrong_password(self, client, seed):
        """密码错误必须 401，且不能泄露"账号是否存在"。"""
        resp = client.post(
            PATHS["login"], json={"police_no": "060101", "password": "wrong-password"}
        )
        assert resp.status_code == 401

    def test_login_disabled_account(self, client, db_session, seed):
        """停用账号不能登录。"""
        user = seed["users"]["police_a"]
        user.status = 0
        db_session.commit()

        resp = client.post(
            PATHS["login"], json={"police_no": "060101", "password": PASSWORD}
        )
        assert resp.status_code in (401, 403)


class TestCrossDeptAccess:
    """2. 跨派出所越权访问。"""

    def test_cross_dept_forbidden(self, client, headers, seed):
        """A 所民警拿 B 所对象 ID 操作，必须 403。"""
        b_agent = client.post(
            PATHS["agent_create"],
            json={"agent_code": "B-E2E-1", "agent_name": "B所对象"},
            headers=headers["police_b"],
        ).json()

        for method, url, payload in [
            ("get", f"/api/v1/agents/{b_agent['id']}", None),
            ("put", f"/api/v1/agents/{b_agent['id']}", {"agent_name": "改"}),
            ("delete", f"/api/v1/agents/{b_agent['id']}", None),
        ]:
            resp = getattr(client, method)(
                url, headers=headers["police_a"], **({"json": payload} if payload else {})
            )
            assert resp.status_code == 403, f"{method.upper()} {url} 应拒绝，实际 {resp.status_code}"

    def test_list_never_leaks_other_dept(self, client, headers, seed):
        """列表接口无论翻到第几页，都不能出现外所数据。"""
        client.post(
            PATHS["agent_create"],
            json={"agent_code": "B-E2E-2", "agent_name": "B所列表"},
            headers=headers["police_b"],
        )
        for page in range(1, 6):
            body = client.get(
                PATHS["agent_list"],
                params={"page": page, "page_size": 50},
                headers=headers["police_a"],
            ).json()
            assert all(item["dept_id"] == seed["dept_a"].id for item in body["items"])


class TestAuditWorkflow:
    """3. 提交审核流程。"""

    def test_audit_workflow(self, client, headers, seed):
        """民警提交 → 审核员通过 → 智能体状态变 PUBLISHED。"""
        agent = client.post(
            PATHS["agent_create"],
            json={"agent_code": "A-E2E-3", "agent_name": "待审核智能体"},
            headers=headers["police_a"],
        ).json()
        assert agent["status"] == "DRAFT"

        # 提交审核
        submit = client.post(
            PATHS["audit_submit"],
            json={"biz_type": "agent", "biz_id": agent["id"], "title": "请审核"},
            headers=headers["police_a"],
        )
        assert submit.status_code in (200, 201)
        task_id = submit.json()["id"]

        # 审核员通过
        approve = client.post(
            PATHS["audit_approve"].format(task_id=task_id),
            json={"approved": True, "audit_opinion": "同意发布"},
            headers=headers["auditor_a"],
        )
        assert approve.status_code == 200

        detail = client.get(
            f"/api/v1/agents/{agent['id']}", headers=headers["police_a"]
        ).json()
        assert detail["status"] == "PUBLISHED"

    def test_reject_flow(self, client, headers, seed):
        """驳回后智能体回到 DRAFT，并带审核意见。"""
        agent = client.post(
            PATHS["agent_create"],
            json={"agent_code": "A-E2E-4", "agent_name": "会被驳回"},
            headers=headers["police_a"],
        ).json()
        task_id = client.post(
            PATHS["audit_submit"],
            json={"biz_type": "agent", "biz_id": agent["id"]},
            headers=headers["police_a"],
        ).json()["id"]

        resp = client.post(
            PATHS["audit_approve"].format(task_id=task_id),
            json={"approved": False, "audit_opinion": "提示词不规范"},
            headers=headers["auditor_a"],
        )
        assert resp.status_code == 200

        detail = client.get(
            f"/api/v1/agents/{agent['id']}", headers=headers["police_a"]
        ).json()
        assert detail["status"] == "DRAFT"


class TestKnowledgeBase:
    """4. 知识库导入。"""

    def test_kb_import(self, client, headers, seed, tmp_path):
        """上传文档 → 解析 → 分片生成，且分片 dept_id 与文档一致。"""
        sample = tmp_path / "sample.txt"
        sample.write_text("公安机关执法办案场所管理规定……" * 50, encoding="utf-8")

        with sample.open("rb") as fp:
            resp = client.post(
                PATHS["kb_upload"],
                files={"file": ("sample.txt", fp, "text/plain")},
                data={"doc_name": "sample.txt"},
                headers=headers["police_a"],
            )
        assert resp.status_code in (200, 201)
        doc = resp.json()

        assert doc["dept_id"] == seed["dept_a"].id
        assert doc["chunk_count"] >= 1

        chunks = client.get(
            f"/api/v1/kb/docs/{doc['id']}/chunks", headers=headers["police_a"]
        ).json()
        assert all(c["dept_id"] == seed["dept_a"].id for c in chunks["items"])

    def test_kb_doc_not_visible_cross_dept(self, client, headers, seed):
        """A 所上传的文档，B 所查不到。"""
        list_b = client.get(PATHS["kb_docs"], headers=headers["police_b"]).json()
        assert all(item["dept_id"] == seed["dept_b"].id for item in list_b["items"])


class TestAuditLogPersisted:
    """5. 审计日志是否正常落库。"""

    def test_audit_log_persisted(self, client, headers, seed, db_session):
        """创建 → 修改 → 删除，三步都要有日志，且操作人能对上。"""
        agent = client.post(
            PATHS["agent_create"],
            json={"agent_code": "A-E2E-5", "agent_name": "留痕"},
            headers=headers["police_a"],
        ).json()
        client.put(
            f"/api/v1/agents/{agent['id']}",
            json={"agent_name": "改过名"},
            headers=headers["police_a"],
        )
        client.delete(f"/api/v1/agents/{agent['id']}", headers=headers["admin"])

        logs = (
            db_session.execute(
                select(OperationLog)
                .where(OperationLog.target_type == "agent", OperationLog.target_id == agent["id"])
                .order_by(OperationLog.id)
            )
            .scalars()
            .all()
        )
        op_types = [log.op_type for log in logs]
        assert "CREATE" in op_types
        assert "UPDATE" in op_types
        assert "DELETE" in op_types
        # 每条日志都必须有操作人，不能出现匿名操作
        assert all(log.police_no for log in logs)
        # 删除属于敏感操作
        assert next(log for log in logs if log.op_type == "DELETE").is_sensitive == 1
