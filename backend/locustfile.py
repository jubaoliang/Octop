"""压测脚本（E-CODE4）—— locust。

运行：
    # 有界面
    locust -f locustfile.py --host http://127.0.0.1:8000

    # 无界面（CI / 快速验证，100 用户跑 3 分钟）
    locust -f locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 100 -r 10 -t 3m --only-summary

    # 只压读接口（跳过登录，需要先手工拿 token）
    locust -f locustfile.py --host http://127.0.0.1:8000 --tags read \
        --headless -u 50 -r 5 -t 1m --only-summary

前置条件
--------
1. 登录接口由 B 提供，默认路径 /api/auth/login，字段 police_no / password。
   路径不一致时改 LOGIN_PATH。
2. 账号来自 scripts/gen_mock_data.py 生成的数据（默认密码 Test@12345）。
3. 读接口 /api/v1/agents 已就绪。

关注指标
--------
- 登录：P95 < 800ms，失败率 < 1%
- 列表查询：P95 < 500ms，失败率 < 1%
- 出现 401 上升 → 检查令牌过期或网关拦截
- 出现 500 → 大概率是数据库连接池耗尽（调 db_pool_size）
"""

from __future__ import annotations

import random

from locust import HttpUser, between, tag, task

LOGIN_PATH = "/api/auth/login"
AGENT_LIST_PATH = "/api/v1/agents"

# gen_mock_data.py 生成的警号规则：前 2 位是所序号（06 起），后 4 位是序号
POLICE_NOS = [f"{dept:02d}{idx:04d}" for dept in range(6, 11) for idx in range(1, 9)]
PASSWORD = "Test@12345"


class PoliceUser(HttpUser):
    """模拟一名登录后的民警。"""

    wait_time = between(1, 3)  # 思考时间，避免脱离真实场景

    def on_start(self) -> None:
        """登录拿 token，失败则后续读请求必然 401，能快速暴露登录问题。"""
        self.token: str | None = None
        self.police_no = random.choice(POLICE_NOS)

        with self.client.post(
            LOGIN_PATH,
            json={"police_no": self.police_no, "password": PASSWORD},
            name="POST /api/auth/login",
            catch_response=True,
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"登录失败 {resp.status_code}: {resp.text[:120]}")
                return
            try:
                body = resp.json()
            except ValueError:
                resp.failure("登录响应不是 JSON")
                return
            # 兼容 {access_token: ...} 与 {data: {access_token: ...}} 两种返回
            data = body.get("data") if isinstance(body.get("data"), dict) else body
            self.token = data.get("access_token") or data.get("token")
            if not self.token:
                resp.failure("响应里没有 access_token")

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @tag("read")
    @task(6)
    def list_agents(self) -> None:
        """查询智能体列表（最热的读接口，带分页）。"""
        if not self.token:
            return
        params = {"page": random.randint(1, 5), "page_size": random.choice([10, 20, 50])}
        with self.client.get(
            AGENT_LIST_PATH,
            params=params,
            headers=self.auth_headers,
            name="GET /api/v1/agents",
            catch_response=True,
        ) as resp:
            if resp.status_code == 401:
                resp.failure("401 未授权，令牌可能失效")
            elif resp.status_code >= 500:
                resp.failure(f"服务端错误 {resp.status_code}")

    @tag("read")
    @task(2)
    def search_agents(self) -> None:
        """带关键词的模糊搜索（走 ilike，容易成为慢查询，重点观察）。"""
        if not self.token:
            return
        with self.client.get(
            AGENT_LIST_PATH,
            params={"keyword": random.choice(["诈骗", "巡逻", "调解", "户籍"]), "page_size": 20},
            headers=self.auth_headers,
            name="GET /api/v1/agents?keyword",
            catch_response=True,
        ) as resp:
            if resp.status_code >= 500:
                resp.failure(f"服务端错误 {resp.status_code}")

    @tag("read")
    @task(1)
    def who_am_i(self) -> None:
        """轻量接口，用来测网关鉴权本身的开销（不含数据库）。"""
        if not self.token:
            return
        self.client.get(
            "/api/v1/me", headers=self.auth_headers, name="GET /api/v1/me"
        )

    @tag("write")
    @task(1)
    def create_agent(self) -> None:
        """写接口：创建智能体并写审计日志。

        ⚠️ 会给测试库造数据，只在测试环境跑；用 --tags read 可排除。
        """
        if not self.token:
            return
        code = f"LOAD-{random.randint(1, 10**9):09d}"
        with self.client.post(
            AGENT_LIST_PATH,
            json={"agent_code": code, "agent_name": f"压测智能体-{code[-4:]}"},
            headers=self.auth_headers,
            name="POST /api/v1/agents",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 201):
                resp.failure(f"创建失败 {resp.status_code}: {resp.text[:120]}")


class AnonymousUser(HttpUser):
    """未登录用户：只压健康检查，验证网关对白名单路径的开销。

    权重设小一点，正常压测时主要是登录用户在跑。
    """

    weight = 1
    wait_time = between(2, 5)

    @task
    def health(self) -> None:
        self.client.get("/health", name="GET /health")
