"""本地快速起服务：用 SQLite 建库 + 建表 + 灌模拟数据。

用途：拿到代码后 5 秒内能把服务跑起来看效果，不需要先装 PostgreSQL。

    python scripts/init_sqlite_dev.py
    PW_DATABASE_URL="sqlite:///./dev.db" uvicorn app.main:app --reload --port 8000

正式联调 / 上线请用 PostgreSQL：
    psql -f sql/01_base_tables.sql && psql -f sql/02_biz_tables.sql
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "dev.db"
os.environ["PW_DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import engine  # noqa: E402
from scripts.gen_mock_data import build_dataset, insert_dataset  # noqa: E402


def main() -> int:
    Base.metadata.create_all(engine)
    print(f"已建表 {len(Base.metadata.tables)} 张 -> {DB_PATH}")

    dataset = build_dataset(dept_count=3, users_per_dept=8, seed=2026)
    created = insert_dataset(dataset, f"sqlite:///{DB_PATH.as_posix()}")
    print(f"已灌数据：部门{created['dept']} 角色{created['role']} 账号{created['user']}")

    print("\n启动服务：")
    print(f'  PW_DATABASE_URL="sqlite:///{DB_PATH.as_posix()}" uvicorn app.main:app --reload --port 8000')
    print("\n拿 token（临时用，正式登录接口由 B 提供）：")
    print(
        '  python -c "import os;os.environ[\'PW_DATABASE_URL\']=\'sqlite:///'
        + DB_PATH.as_posix()
        + '\';import sys;sys.path.insert(0,\'.\');'
        'from app.core.security import create_access_token;'
        "print(create_access_token(2, police_no='060001', dept_id=2, roles=['police'], data_scope='DEPT'))\""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
