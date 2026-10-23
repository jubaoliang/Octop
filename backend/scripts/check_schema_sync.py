"""建表 SQL ←→ ORM 模型 一致性检查（整理期加的自查工具）。

为什么需要它：
    SQL 是给人执行 DDL 的，ORM 是给程序跑查询的，两边一漂移就会出现
    "本地能跑、上线报列不存在"，或者更糟——ORM 里少了个 NOT NULL，
    测试库放行了脏数据，生产库直接拒绝。这个脚本把漂移变成一次可见的报告。

检查项：
    1. 表：SQL 有 / ORM 没有，ORM 有 / SQL 没有
    2. 列：同上
    3. 可空性：NOT NULL 是否一致
    4. 类型族：BIGINT / VARCHAR / TIMESTAMP 等是否对得上
    5. 硬约束：业务表必须有 dept_id 且 NOT NULL（行级隔离的地基）

用法：
    python scripts/check_schema_sync.py          # 有差异时退出码 1，可挂 CI
    python scripts/check_schema_sync.py -v       # 打印每张表的列数
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import (  # noqa: E402
    BigInteger,
    DateTime,
    Integer,
    JSON,
    SmallInteger,
    String,
    Text,
)

import app.models  # noqa: E402,F401  触发模型注册
from app.db.base import Base  # noqa: E402

SQL_DIR = BASE_DIR / "sql"

# ---------------------------------------------------------------------------
# SQL 解析
# ---------------------------------------------------------------------------
CREATE_TABLE_RE = re.compile(
    r'CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+"?(\w+)"?\s*\((.*?)\n\);',
    re.IGNORECASE | re.DOTALL,
)
COLUMN_RE = re.compile(r"^\s{4}([a-z_][a-z0-9_]*)\s+([A-Za-z][A-Za-z0-9]*(?:\([^)]*\))?)(.*)$")
# 这些行不是列定义
NON_COLUMN_PREFIX = (
    "constraint",
    "primary key",
    "unique",
    "check",
    "foreign key",
    "on delete",
)

# 只检查业务表是否带 dept_id；系统表里 dept 本身、role 等不需要
SYSTEM_TABLES = {"dept", "user_police", "role", "user_role", "role_perm", "operation_log", "message"}


def parse_sql_schema() -> dict[str, dict[str, dict]]:
    """解析 sql/*.sql，返回 {表名: {列名: {"nullable": bool, "type": str}}}。"""
    schema: dict[str, dict[str, dict]] = {}

    for path in sorted(SQL_DIR.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        # 去掉行注释，避免把 "-- xxx" 当列
        text = re.sub(r"--[^\n]*", "", text)

        for table, body in CREATE_TABLE_RE.findall(text):
            columns: dict[str, dict] = {}
            for raw_line in body.splitlines():
                line = raw_line.rstrip()
                if not line.strip():
                    continue
                lowered = line.strip().lower()
                if lowered.startswith(NON_COLUMN_PREFIX):
                    continue

                match = COLUMN_RE.match(line)
                if not match:
                    continue

                name, col_type, rest = match.groups()
                is_pk = "PRIMARY KEY" in rest.upper()
                columns[name] = {
                    "nullable": not is_pk and "NOT NULL" not in rest.upper(),
                    "type": col_type.upper(),
                    "source": path.name,
                }
            if columns:
                schema[table] = columns

    return schema


# ---------------------------------------------------------------------------
# ORM 解析
# ---------------------------------------------------------------------------
def orm_type_family(col_type) -> str:
    """把 SQLAlchemy 类型归到粗粒度族，避免 VARCHAR(64) vs String(64) 这类误报。"""
    if isinstance(col_type, BigInteger):
        return "bigint"
    if isinstance(col_type, SmallInteger):
        return "smallint"
    if isinstance(col_type, Integer):
        return "integer"
    if isinstance(col_type, JSON):
        return "json"
    if isinstance(col_type, DateTime):
        return "timestamp"
    # 注意顺序：Text 继承自 String，必须先判 Text，否则 TEXT 会被误认成 VARCHAR
    if isinstance(col_type, Text):
        return "text"
    if isinstance(col_type, String):
        return "string"
    return "other"


def sql_type_family(sql_type: str) -> str:
    """把 SQL 类型串归到同一套族。"""
    t = sql_type.upper()
    if t.startswith("BIGSERIAL") or t.startswith("BIGINT"):
        return "bigint"
    if t.startswith("SMALLINT"):
        return "smallint"
    if t.startswith("SERIAL") or t.startswith("INTEGER") or t == "INT":
        return "integer"
    if t.startswith("JSON"):
        return "json"
    if t.startswith("TIMESTAMP") or t.startswith("DATETIME"):
        return "timestamp"
    if t.startswith("VARCHAR") or t.startswith("CHARACTER") or t.startswith("CHAR"):
        return "string"
    if t.startswith("TEXT"):
        return "text"
    return "other"


def parse_orm_schema() -> dict[str, dict[str, dict]]:
    """从 Base.metadata 取 ORM 侧结构。"""
    schema: dict[str, dict[str, dict]] = {}
    for table_name, table in Base.metadata.tables.items():
        columns: dict[str, dict] = {}
        for column in table.columns:
            columns[column.name] = {
                "nullable": bool(column.nullable),
                "type": orm_type_family(column.type),
                "source": "models",
            }
        schema[table_name] = columns
    return schema


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------
def compare(verbose: bool = False) -> int:
    sql_schema = parse_sql_schema()
    orm_schema = parse_orm_schema()

    issues: list[str] = []
    lines: list[str] = []

    only_sql = sorted(set(sql_schema) - set(orm_schema))
    only_orm = sorted(set(orm_schema) - set(sql_schema))
    common = sorted(set(sql_schema) & set(orm_schema))

    lines.append("=" * 66)
    lines.append("表结构一致性检查：sql/*.sql  <——>  app/models/*.py")
    lines.append(f"表数量：SQL {len(sql_schema)} 张 / ORM {len(orm_schema)} 张")
    lines.append("=" * 66)

    for table in only_sql:
        issues.append(f"[表缺失] {table}：SQL 有建表，ORM 没有对应模型")
    for table in only_orm:
        issues.append(f"[表缺失] {table}：ORM 有模型，SQL 没有建表")

    for table in common:
        sql_cols = sql_schema[table]
        orm_cols = orm_schema[table]
        table_issues: list[str] = []

        for col in sorted(set(sql_cols) - set(orm_cols)):
            table_issues.append(f"列 {col}：SQL 有，ORM 缺")
        for col in sorted(set(orm_cols) - set(sql_cols)):
            table_issues.append(f"列 {col}：ORM 有，SQL 缺")

        for col in sorted(set(sql_cols) & set(orm_cols)):
            s, o = sql_cols[col], orm_cols[col]
            if s["nullable"] != o["nullable"]:
                table_issues.append(
                    f"列 {col}：可空性不一致（SQL={'NULL' if s['nullable'] else 'NOT NULL'}，"
                    f"ORM={'NULL' if o['nullable'] else 'NOT NULL'}）"
                )
            s_family = sql_type_family(s["type"])
            if s_family != o["type"] and "other" not in (s_family, o["type"]):
                table_issues.append(
                    f"列 {col}：类型不一致（SQL={s['type']} → {s_family}，ORM → {o['type']}）"
                )

        # 业务表硬约束
        if table not in SYSTEM_TABLES:
            if "dept_id" not in orm_cols:
                table_issues.append("业务表缺 dept_id 列 —— 行级隔离会失效")
            elif orm_cols["dept_id"]["nullable"]:
                table_issues.append("dept_id 允许为空 —— 行级隔离会出现'谁都看不见'的数据")

        if table_issues:
            issues.extend(f"[{table}] {item}" for item in table_issues)
            lines.append(f"[差异] {table:16} {len(table_issues)} 处")
        else:
            note = f"{len(sql_cols)} 列，一致" if verbose else "OK"
            lines.append(f"[通过] {table:16} {note}")

    lines.append("-" * 66)
    if issues:
        lines.append(f"发现 {len(issues)} 处差异：")
        lines.extend(f"  · {item}" for item in issues)
        lines.append("")
        lines.append("修法：同步改 sql/ 与 app/models/，两边都改完再跑一次本脚本。")
    else:
        lines.append("全部一致，SQL 与 ORM 没有漂移。")

    print("\n".join(lines))
    return 1 if issues else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查建表 SQL 与 ORM 模型是否一致")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每张表的列数")
    args = parser.parse_args()

    if not SQL_DIR.exists():
        print(f"找不到 SQL 目录：{SQL_DIR}")
        return 2

    return compare(verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
