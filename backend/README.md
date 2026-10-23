# 民警工作台后端 · 基础层（D / E 先行代码）

Python + FastAPI + PostgreSQL。当前交付的是**基础层**：建表 SQL、鉴权、行级权限、审计、脱敏、测试脚手架。
业务接口（智能体/模板/审核/知识库）等 B 的字段清单到位后基于这套地基往上写。

## 目录

```
backend/                   ← 所有代码都在这一个文件夹里
├── app/
│   ├── core/             配置 / JWT / 上下文 / 鉴权依赖 / 网关中间件
│   │   ├── config.py        所有配置，环境变量前缀 PW_
│   │   ├── security.py      JWT 签发与校验
│   │   ├── context.py       CurrentUser + ContextVar（权限装饰器的取值来源）
│   │   ├── deps.py          get_current_user / require_roles
│   │   └── middleware.py    纯 ASGI 鉴权中间件（白名单 + 401）
│   ├── db/                 声明基类 / 连接会话
│   ├── models/             ORM 模型（与 sql/ 严格对应）
│   ├── schemas/            Pydantic 模型（Create / Update / Out）
│   ├── utils/
│   │   ├── audit.py         write_operation_log
│   │   ├── permission.py    filter_by_dept / apply_dept_filter / ensure_dept_access
│   │   └── desensitize.py   手机号 / 身份证 / 姓名 / 地址脱敏
│   ├── routers/demo_agent.py  业务接入示例（给 B 参考）
│   └── main.py             应用入口
├── sql/
│   ├── 01_base_tables.sql     7 张基础表 + 触发器 + 初始角色
│   ├── 02_biz_tables.sql      6 张业务表（占位，待 B 字段确认）
│   └── 99_isolation_check.sql 越权校验 SQL（手工/联调时跑）
├── tests/                 64 条已通过用例 + pytest 脚手架
├── scripts/
│   ├── gen_mock_data.py      模拟数据生成（JSON / 直接入库）
│   ├── init_sqlite_dev.py    本地 5 秒起服务
│   └── check_schema_sync.py  建表 SQL ←→ ORM 一致性自查
└── locustfile.py          压测脚本
```

## 快速开始

**方式一：不装 PostgreSQL，本地直接看效果**

```bash
cd backend                                   # 下面所有命令都以这个目录为根
pip install -r requirements.txt
python scripts/init_sqlite_dev.py            # 建表 + 灌 4 个所 25 个账号
PW_DATABASE_URL="sqlite:///./dev.db" uvicorn app.main:app --reload --port 8000
# http://127.0.0.1:8000/docs
```

**方式二：PostgreSQL（正式联调）**

```bash
psql -U postgres -d police_workbench -f sql/01_base_tables.sql
psql -U postgres -d police_workbench -f sql/02_biz_tables.sql
cp .env.example .env        # 改 PW_DATABASE_URL / PW_JWT_SECRET
uvicorn app.main:app --port 8000
```

**跑测试**

```bash
pytest                       # 64 passed, 10 skipped（e2e 等 B 接口）
pytest -m "not e2e" -v
```

**改完字段必跑这一条**

```bash
python scripts/check_schema_sync.py      # SQL 与 ORM 有没有漂移，有差异退出码 1
```

它会比对 13 张表的列名、可空性、类型族，并强制检查每张业务表都带非空 `dept_id`。
改字段时最容易只改一边（SQL 改了忘了 ORM，或反过来），这条命令能在提交前拦住。


## 三条硬约定（改代码前先看）

1. **dept_id 只从令牌取，永不信请求体。**
   所有 Create 模型里都没有 dept_id 字段，多传会 422；写库时统一 `dept_id=user.dept_id`。

2. **拿不到 dept_id 时 fail-closed。**
   已登录但令牌缺部门 → 追加 `1=0`，查不到数据；未登录 → 401。绝不做"不过滤"的兜底。

3. **业务表必须有 dept_id 列。**
   行级隔离靠这个字段，新增表时漏了，`filter_by_dept` 会直接抛 DeptScopeError 而不是放行。

## 权限装饰器为什么是两层

只在装饰器里改"传进来的语句"挡不住函数体内 `select()` 出来的查询，所以：

- **语句级**：参数/返回值里是 Select → 直接追加 where
- **Session 级**：调用期间给 Session 挂 `do_orm_execute` 监听，函数内所有 ORM SELECT 自动叠加 `with_loader_criteria`，执行完立刻卸载

第二层是真正的兜底：业务同学忘写过滤条件，也漏不出数据（`tests/test_permission.py::test_session_level_auto_filter` 覆盖了这个场景）。

## 当前状态

| 指令 | 状态 | 位置 |
|---|---|---|
| D-CODE1 基础建表 SQL | 完成 | `sql/01_base_tables.sql` |
| D-CODE2 审计日志工具 | 完成 | `app/utils/audit.py` |
| D-CODE3 行级权限装饰器 | 完成（两层机制） | `app/utils/permission.py` |
| D-CODE4 脱敏工具 | 完成 | `app/utils/desensitize.py` |
| D-CODE5 JWT 鉴权 | 完成（依赖 + 中间件） | `app/core/deps.py`、`middleware.py` |
| D-CODE6 Pydantic 模型 | 完成 | `app/schemas/` |
| D-CODE7 业务表 SQL | **占位，等 B 字段** | `sql/02_biz_tables.sql` |
| D-CODE8 业务 Schema | 占位，等 B 字段 | `app/schemas/biz.py` |
| D-CODE9 接入示例路由 | 完成 | `app/routers/demo_agent.py` |
| D-CODE10 越权校验 SQL | 完成 | `sql/99_isolation_check.sql` |
| E-CODE1 pytest 脚手架 | 完成 | `tests/conftest.py` |
| E-CODE2 模拟数据脚本 | 完成 | `scripts/gen_mock_data.py` |
| E-CODE3 自动化用例 | 已写好，skip 待启用 | `tests/test_business_e2e.py` |
| E-CODE4 locust 压测 | 完成 | `locustfile.py` |
| 补充：密码哈希 | 完成（bcrypt，B 登录接口直接用） | `app/core/security.py` |
| 补充：SQL/ORM 一致性自查 | 完成 | `scripts/check_schema_sync.py` |

D-CODE7 / D-CODE8 拿到 B 的字段清单后，只改两个文件：`sql/02_biz_tables.sql` + `app/models/biz.py`，
权限和审计代码一行都不用动。

## 待办（需要外部输入）

- B 的字段清单 → 定稿业务表（D-CODE7/D-CODE8）
- B 的登录接口路径 → 打开 `tests/test_business_e2e.py` 的 skip，跑通 E-CODE3
- 登录接口就绪后，`get_current_user` 不需要改，令牌签发逻辑已在 `app/core/security.py`
