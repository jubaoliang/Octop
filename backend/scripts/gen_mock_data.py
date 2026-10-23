"""模拟警务测试数据生成脚本（E-CODE2）。

功能
----
批量生成：派出所（含 1 个分局作为上级）、警员账号、警号、角色绑定。
两种用法：

    # 1) 只生成 JSON，本地测试/前端 mock 用
    python scripts/gen_mock_data.py --depts 5 --users-per-dept 8 -o mock_data.json

    # 2) 直接灌进测试库（会清空同名 dept_code / police_no 之外的数据？不会，只做插入去重）
    python scripts/gen_mock_data.py --depts 5 --users-per-dept 8 \
        --insert --dsn "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/police_workbench"

    # 3) 指定随机种子，保证多次运行结果一致（方便复现 bug）
    python scripts/gen_mock_data.py --seed 42 -o mock_data.json

生成规则
--------
- 警号：前 2 位区分派出所（06/07/08...）+ 4 位序号，如 06 所第 1 号 = 060001
- 手机号：统一 138 开头 11 位，保证通过脱敏规则验证
- 身份证号：110101 + 合法长度 18 位（不校验校验位，测试数据够用）
- 密码：统一 Test@12345，落库时用 pbkdf2 哈希（生产请换 bcrypt/passlib）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime
from pathlib import Path

# 项目根目录（backend/），插入 sys.path 后才能 import app.*
BASE_DIR = Path(__file__).resolve().parent.parent

# 派出所名字素材
DEPT_PREFIX = ["东城", "西城", "南湖", "北岸", "长江路", "解放路", "高新", "临江", "望湖", "青云"]
DEPT_SUFFIX = ["派出所", "派出所", "派出所", "警务站"]

SURNAMES = list("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜")
GIVEN_NAMES = ["建国", "志强", "海涛", "晓东", "文斌", "丽娜", "婷婷", "秀英", "国强", "明辉",
               "小军", "佳怡", "振华", "雪梅", "永刚", "春燕", "卫国", "红梅", "俊杰", "婉如"]

RANKS = ["一级警督", "二级警督", "三级警督", "一级警司", "二级警司", "三级警司", "一级警员", "二级警员"]
POSTS = ["所长", "副所长", "教导员", "民警", "民警", "民警", "辅警"]

ROLE_DEFS = [
    {"role_code": "admin", "role_name": "系统管理员", "data_scope": "ALL", "description": "跨所管理"},
    {"role_code": "police", "role_name": "普通民警", "data_scope": "DEPT", "description": "本所数据"},
    {"role_code": "auditor", "role_name": "审核员", "data_scope": "DEPT", "description": "审核本所业务"},
]

DEFAULT_PASSWORD = "Test@12345"


def hash_password(password: str, salt: str = "mock-salt") -> str:
    """pbkdf2 哈希（仅测试用；生产用 bcrypt）。

    生成格式：pbkdf2_sha256$<iterations>$<salt>$<hex>
    """
    iterations = 120_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def build_dataset(
    dept_count: int = 5,
    users_per_dept: int = 8,
    seed: int | None = None,
    included_admin: bool = True,
) -> dict:
    """构造完整数据集（纯内存，不碰数据库）。"""
    rng = random.Random(seed)

    depts: list[dict] = []
    # 1. 分局（顶级）
    branch = {
        "dept_code": "FJ001",
        "dept_name": "示范区分局",
        "parent_code": None,
        "dept_level": 1,
        "region_code": "110101",
        "address": "示范区公安分局办公大楼",
        "leader_name": f"{rng.choice(SURNAMES)}局",
        "leader_phone": "13800000000",
        "sort_no": 0,
    }
    depts.append(branch)

    # 2. 派出所
    used_names: set[str] = set()
    for i in range(dept_count):
        prefix = DEPT_PREFIX[i % len(DEPT_PREFIX)]
        name = prefix + DEPT_SUFFIX[i % len(DEPT_SUFFIX)]
        if name in used_names:  # 避免重名
            name = f"{name}{i + 1}"
        used_names.add(name)
        depts.append(
            {
                "dept_code": f"PCS{i + 1:03d}",
                "dept_name": name,
                "parent_code": "FJ001",
                "dept_level": 3,
                "region_code": f"11010{i % 10}",
                "address": f"示范区{prefix}路{i + 1}号",
                "leader_name": rng.choice(SURNAMES) + rng.choice(GIVEN_NAMES),
                "leader_phone": f"138{rng.randint(10000000, 99999999)}",
                "sort_no": i + 1,
            }
        )

    # 3. 警员
    users: list[dict] = []
    seq = 0

    def _mk_user(dept_code: str, dept_no: int, role_code: str, idx: int) -> dict:
        nonlocal seq
        seq += 1
        police_no = f"{dept_no:02d}{idx:04d}"
        return {
            "police_no": police_no,
            "real_name": rng.choice(SURNAMES) + rng.choice(GIVEN_NAMES),
            "dept_code": dept_code,
            "role_codes": [role_code],
            "phone": f"138{rng.randint(10000000, 99999999)}",
            "id_card": f"110101{rng.randint(1970, 2000)}{rng.randint(1, 12):02d}"
                       f"{rng.randint(1, 28):02d}{rng.randint(1000, 9999)}",
            "gender": rng.choice([1, 1, 2]),
            "rank_name": rng.choice(RANKS),
            "post_name": rng.choice(POSTS),
            "status": 1,
            "password": DEFAULT_PASSWORD,
            "password_hash": hash_password(DEFAULT_PASSWORD, police_no),
        }

    if included_admin:
        users.append(
            {
                "police_no": "000001",
                "real_name": "分局管理员",
                "dept_code": "FJ001",
                "role_codes": ["admin"],
                "phone": "13800000001",
                "id_card": "110101198001011234",
                "gender": 1,
                "rank_name": "一级警督",
                "post_name": "系统管理员",
                "status": 1,
                "password": DEFAULT_PASSWORD,
                "password_hash": hash_password(DEFAULT_PASSWORD, "000001"),
            }
        )

    for i in range(dept_count):
        dept_code = f"PCS{i + 1:03d}"
        for j in range(users_per_dept):
            # 每个所前 2 个给审核员角色，其余民警
            role = "auditor" if j < 2 else "police"
            users.append(_mk_user(dept_code, i + 6, role, j + 1))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "default_password": DEFAULT_PASSWORD,
        "roles": ROLE_DEFS,
        "depts": depts,
        "users": users,
        "stats": {
            "dept_count": len(depts),
            "user_count": len(users),
            "police_count": sum(1 for u in users if "police" in u["role_codes"]),
            "auditor_count": sum(1 for u in users if "auditor" in u["role_codes"]),
        },
    }


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
def insert_dataset(dataset: dict, dsn: str) -> dict:
    """把数据集写入数据库（幂等：已存在的 dept_code / police_no 跳过）。"""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    # 复用项目模型，保证与建表 SQL 一致
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from app.models.system import Dept, Role, UserPolice, UserRole  # noqa: E402

    engine = create_engine(dsn, future=True)
    created = {"dept": 0, "user": 0, "user_role": 0, "role": 0}

    with Session(engine, expire_on_commit=False) as session:
        # 1) 角色
        role_map: dict[str, Role] = {}
        for item in dataset["roles"]:
            role = session.execute(
                select(Role).where(Role.role_code == item["role_code"])
            ).scalar_one_or_none()
            if role is None:
                role = Role(
                    role_code=item["role_code"],
                    role_name=item["role_name"],
                    data_scope=item["data_scope"],
                    description=item["description"],
                    status=1,
                    is_deleted=0,
                )
                session.add(role)
                session.flush()
                created["role"] += 1
            role_map[item["role_code"]] = role

        # 2) 部门（先分局后派出所，保证 parent 能对上）
        dept_map: dict[str, Dept] = {}
        for item in sorted(dataset["depts"], key=lambda d: d["dept_level"]):
            dept = session.execute(
                select(Dept).where(Dept.dept_code == item["dept_code"])
            ).scalar_one_or_none()
            if dept is None:
                parent_id = None
                if item.get("parent_code"):
                    parent = dept_map.get(item["parent_code"])
                    parent_id = parent.id if parent else None
                dept = Dept(
                    dept_code=item["dept_code"],
                    dept_name=item["dept_name"],
                    parent_id=parent_id,
                    dept_level=item["dept_level"],
                    region_code=item.get("region_code"),
                    address=item.get("address"),
                    leader_name=item.get("leader_name"),
                    leader_phone=item.get("leader_phone"),
                    sort_no=item.get("sort_no", 0),
                    status=1,
                    is_deleted=0,
                )
                session.add(dept)
                session.flush()
                created["dept"] += 1
            dept_map[item["dept_code"]] = dept

        # 3) 警员 + 角色关联
        for item in dataset["users"]:
            exists = session.execute(
                select(UserPolice.id).where(UserPolice.police_no == item["police_no"])
            ).first()
            if exists:
                continue
            dept = dept_map.get(item["dept_code"])
            if dept is None:
                print(f"  ! 跳过 {item['police_no']}：找不到部门 {item['dept_code']}")
                continue
            user = UserPolice(
                police_no=item["police_no"],
                real_name=item["real_name"],
                password_hash=item["password_hash"],
                dept_id=dept.id,
                phone=item.get("phone"),
                id_card=item.get("id_card"),
                gender=item.get("gender", 0),
                rank_name=item.get("rank_name"),
                post_name=item.get("post_name"),
                status=item.get("status", 1),
                is_deleted=0,
            )
            session.add(user)
            session.flush()
            created["user"] += 1

            for code in item["role_codes"]:
                role = role_map.get(code)
                if role is None:
                    continue
                session.add(UserRole(user_id=user.id, role_id=role.id))
                created["user_role"] += 1

        session.commit()

    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="生成模拟警务测试数据")
    parser.add_argument("--depts", type=int, default=5, help="派出所数量")
    parser.add_argument("--users-per-dept", type=int, default=8, help="每个所警员数量")
    parser.add_argument("--seed", type=int, default=None, help="随机种子，便于复现")
    parser.add_argument("-o", "--output", default="mock_data.json", help="JSON 输出路径")
    parser.add_argument("--insert", action="store_true", help="写入数据库")
    parser.add_argument(
        "--dsn",
        default="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/police_workbench",
        help="数据库连接串（--insert 时使用）",
    )
    parser.add_argument("--no-admin", action="store_true", help="不生成分局管理员")
    args = parser.parse_args()

    dataset = build_dataset(
        dept_count=args.depts,
        users_per_dept=args.users_per_dept,
        seed=args.seed,
        included_admin=not args.no_admin,
    )

    output = Path(args.output)
    output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stats = dataset["stats"]
    print(f"已生成 {output}：{stats['dept_count']} 个部门 / {stats['user_count']} 个账号")
    print(f"  默认密码：{DEFAULT_PASSWORD}")
    print("  示例账号：" + "、".join(u["police_no"] for u in dataset["users"][:5]))

    if args.insert:
        print(f"正在写入数据库：{args.dsn}")
        created = insert_dataset(dataset, args.dsn)
        print(
            f"  新增 部门{created['dept']} / 角色{created['role']} / "
            f"账号{created['user']} / 角色绑定{created['user_role']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
