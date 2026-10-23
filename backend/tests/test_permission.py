"""权限与数据隔离测试（E-CODE1 · test_login_permission / test_data_isolate）。

覆盖：
1. 鉴权：无 token、伪造 token、过期逻辑 → 401
2. 数据隔离：A 所只能看本所数据，跨所访问详情 → 403
3. 管理员 data_scope=ALL → 看全量
4. 写入时 dept_id 强制取登录态，前端传不进来
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security import create_access_token
from app.models.biz import Agent
from app.utils.permission import apply_dept_filter


class TestLoginPermission:
    """test_login_permission：网关鉴权链路。"""

    def test_no_token_gets_401(self, client):
        """白名单外不带 token，网关层直接 401。"""
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 401
        assert resp.json()["code"] == "TOKEN_MISSING"

    def test_invalid_token_gets_401(self, client):
        """伪造/篡改的 token 一律 401。"""
        resp = client.get(
            "/api/v1/agents", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "TOKEN_INVALID"

    def test_wrong_secret_token_gets_401(self, client):
        """用别的密钥签发的 token 不能被信任。"""
        import jwt

        forged = jwt.encode(
            {"sub": "1", "dept_id": 1, "data_scope": "ALL", "exp": 9999999999},
            "attacker-secret",
            algorithm="HS256",
        )
        resp = client.get("/api/v1/agents", headers={"Authorization": f"Bearer {forged}"})
        assert resp.status_code == 401

    def test_valid_token_can_access(self, client, headers, seed):
        """合法 token 正常进入业务。"""
        resp = client.get("/api/v1/agents", headers=headers["police_a"])
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_me_returns_identity(self, client, headers, seed):
        """身份信息能正确从令牌里解析出来。"""
        resp = client.get("/api/v1/me", headers=headers["police_a"])
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["police_no"] == "060101"
        assert body["dept_id"] == seed["dept_a"].id
        assert body["data_scope"] == "DEPT"

    def test_role_guard_blocks_normal_police(self, client, headers, seed):
        """/agents/{id} 删除需要 admin，普通民警 403。"""
        created = client.post(
            "/api/v1/agents",
            json={"agent_code": "A-100", "agent_name": "待删智能体"},
            headers=headers["police_a"],
        ).json()
        resp = client.delete(f"/api/v1/agents/{created['id']}", headers=headers["police_a"])
        assert resp.status_code == 403

    def test_health_is_whitelisted(self, client):
        """健康检查在白名单里，不需要令牌。"""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestDataIsolate:
    """test_data_isolate：派出所行级隔离。"""

    def _create(self, client, headers, code: str, name: str) -> dict:
        resp = client.post(
            "/api/v1/agents",
            json={"agent_code": code, "agent_name": name},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_each_dept_sees_only_own(self, client, headers, seed):
        """A 所只能看到 A 所的智能体，B 所的看不到。"""
        a_agent = self._create(client, headers["police_a"], "A-001", "A所智能体")
        b_agent = self._create(client, headers["police_b"], "B-001", "B所智能体")

        assert a_agent["dept_id"] == seed["dept_a"].id
        assert b_agent["dept_id"] == seed["dept_b"].id

        body = client.get("/api/v1/agents", headers=headers["police_a"]).json()
        codes = [item["agent_code"] for item in body["items"]]
        assert body["total"] == 1
        assert codes == ["A-001"]

        body_b = client.get("/api/v1/agents", headers=headers["police_b"]).json()
        assert body_b["total"] == 1
        assert [i["agent_code"] for i in body_b["items"]] == ["B-001"]

    def test_cross_dept_detail_is_forbidden(self, client, headers, seed):
        """拿 B 所的 agent_id 去 A 所查详情 → 403。"""
        b_agent = self._create(client, headers["police_b"], "B-002", "B所详情测试")

        resp = client.get(f"/api/v1/agents/{b_agent['id']}", headers=headers["police_a"])
        assert resp.status_code == 403
        assert resp.json()["code"] == "DEPT_SCOPE_DENIED"

    def test_cross_dept_update_is_forbidden(self, client, headers, seed):
        """跨所修改 → 403。"""
        b_agent = self._create(client, headers["police_b"], "B-003", "B所修改测试")

        resp = client.put(
            f"/api/v1/agents/{b_agent['id']}",
            json={"agent_name": "被篡改"},
            headers=headers["police_a"],
        )
        assert resp.status_code == 403

    def test_admin_sees_all_depts(self, client, headers, seed):
        """data_scope=ALL 的管理员不加过滤。"""
        self._create(client, headers["police_a"], "A-002", "A所")
        self._create(client, headers["police_b"], "B-004", "B所")

        body = client.get("/api/v1/agents", headers=headers["admin"]).json()
        assert body["total"] == 2

    def test_create_ignores_client_supplied_dept_id(self, client, headers, seed):
        """前端硬塞 dept_id 无效：服务端只认登录态。

        AgentCreate 用了 extra=forbid，多传 dept_id 会被 422 挡掉；
        即使模型放开，代码路径也是 agent.dept_id = user.dept_id，不会读请求体。
        """
        resp = client.post(
            "/api/v1/agents",
            json={"agent_code": "A-003", "agent_name": "越权尝试", "dept_id": seed["dept_b"].id},
            headers=headers["police_a"],
        )
        assert resp.status_code == 422

        ok = client.post(
            "/api/v1/agents",
            json={"agent_code": "A-004", "agent_name": "正常创建"},
            headers=headers["police_a"],
        )
        assert ok.status_code == 201
        assert ok.json()["dept_id"] == seed["dept_a"].id

    def test_session_level_auto_filter(self, client, headers, seed, db_session):
        """Session 事件级过滤：即使语句里没写 dept_id 条件，也查不到外所数据。

        这是装饰器最关键的兜底能力 —— 业务同学漏写条件也漏不了数据。
        """
        client.post(
            "/api/v1/agents",
            json={"agent_code": "A-005", "agent_name": "A所"},
            headers=headers["police_a"],
        )
        client.post(
            "/api/v1/agents",
            json={"agent_code": "B-005", "agent_name": "B所"},
            headers=headers["police_b"],
        )

        from app.core.context import build_current_user, reset_current_user, set_current_user
        from app.utils.permission import _install_session_scope, _uninstall_session_scope

        ctx = set_current_user(
            build_current_user(
                {
                    "sub": seed["users"]["police_a"].id,
                    "police_no": "060101",
                    "dept_id": seed["dept_a"].id,
                    "roles": ["police"],
                    "data_scope": "DEPT",
                }
            )
        )
        try:
            listener = _install_session_scope(db_session, seed["dept_a"].id, Agent, "dept_id")
            try:
                # 故意不写任何 dept_id 条件
                rows = db_session.execute(select(Agent)).scalars().all()
            finally:
                _uninstall_session_scope(db_session, listener)
            assert {r.agent_code for r in rows} == {"A-005"}
        finally:
            reset_current_user(ctx)


class TestScopeSafety:
    """fail-closed 行为：拿不到 dept_id 时宁可查不到。"""

    def test_apply_filter_with_none_dept(self):
        stmt = apply_dept_filter(select(Agent), dept_id=None, model=Agent)
        sql = str(stmt)
        assert "1 != 1" in sql or "false" in sql.lower()

    def test_apply_filter_adds_dept_condition(self, seed):
        stmt = apply_dept_filter(select(Agent), dept_id=seed["dept_a"].id, model=Agent)
        assert "dept_id" in str(stmt)

    def test_model_without_dept_column_raises(self):
        from app.models.system import Message
        from app.utils.permission import DeptScopeError

        with pytest.raises(DeptScopeError):
            apply_dept_filter(select(Message), dept_id=1, model=Message)
