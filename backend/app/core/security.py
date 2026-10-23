"""JWT 令牌签发与校验（D-CODE5 的底层实现）。

只负责「造令牌」和「验令牌」两件事，不碰任何登录业务逻辑。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


# ---------------------------------------------------------------------------
# 异常定义：统一携带 HTTP 状态码，方便依赖层直接转成 401
# ---------------------------------------------------------------------------
class TokenError(Exception):
    """令牌非法（签名错误、格式错误、缺少必要字段等）。"""

    status_code = 401
    error_code = "TOKEN_INVALID"

    def __init__(self, detail: str = "令牌非法或已失效"):
        self.detail = detail
        super().__init__(detail)


class TokenExpiredError(TokenError):
    """令牌已过期。"""

    error_code = "TOKEN_EXPIRED"

    def __init__(self, detail: str = "登录状态已过期，请重新登录"):
        super().__init__(detail)


# ---------------------------------------------------------------------------
# 签发
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: int,
    *,
    police_no: str | None = None,
    dept_id: int | None = None,
    roles: list[str] | None = None,
    data_scope: str = "DEPT",
    expires_minutes: int | None = None,
    extra: dict | None = None,
) -> str:
    """签发一个 access_token。

    Args:
        user_id: 用户主键，写入 sub（JWT 规范要求 sub 为字符串，解码时转回 int）。
        police_no: 警号，写进令牌后业务层无需再查库。
        dept_id: 所属派出所 ID —— 行级数据隔离的唯一依据。
        roles: 角色编码列表，如 ["police"]。
        data_scope: 数据范围。ALL=全局（分局管理员），DEPT=本所，SELF=仅本人。
        expires_minutes: 有效期，默认取配置。
        extra: 需要额外塞进令牌的自定义字段。

    Returns:
        编码后的 JWT 字符串。
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )

    payload: dict = {
        "sub": str(user_id),          # 主体：用户 ID
        "police_no": police_no,        # 警号
        "dept_id": dept_id,            # 派出所 ID（行级隔离关键字段）
        "roles": roles or [],          # 角色列表
        "data_scope": data_scope,      # 数据范围
        "iat": int(now.timestamp()),   # 签发时间
        "exp": int(expire.timestamp()),# 过期时间
        "jti": uuid.uuid4().hex,       # 令牌唯一 ID，便于后续做主动失效/黑名单
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def decode_access_token(token: str) -> dict:
    """解析并校验令牌，失败时抛出 TokenError / TokenExpiredError。

    Returns:
        解码后的 payload 字典（sub 已转成 int）。
    """
    if not token or not token.strip():
        raise TokenError("缺少身份令牌")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("令牌非法或已失效") from exc

    # sub 在 JWT 里是字符串，这里统一转成 int，业务层拿到的就是用户 ID
    try:
        payload["sub"] = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("令牌缺少有效的用户标识") from exc

    return payload


def parse_bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 头里取 Bearer 令牌，格式不对返回 None。"""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


# ---------------------------------------------------------------------------
# 密码哈希：B 写登录接口时直接调这两个函数，别自己造
# ---------------------------------------------------------------------------
# bcrypt 的算法上限是 72 字节（注意是字节不是字符，一个汉字 3 字节 → 24 个汉字就到顶），
# 超长部分会被算法忽略，因此这里显式截断，避免"密码后半段没生效"的隐式坑。
_BCRYPT_MAX_BYTES = 72
DEFAULT_BCRYPT_ROUNDS = 12


def hash_password(password: str, *, rounds: int = DEFAULT_BCRYPT_ROUNDS) -> str:
    """生成密码哈希，返回可直接存进 user_police.password_hash 的字符串。

    Args:
        password: 明文密码。
        rounds: bcrypt 计算轮数，默认 12（约 250ms，兼顾安全与登录延迟）。
                单测里可以传 4 提速。

    Raises:
        ValueError: 密码为空。
    """
    if not password:
        raise ValueError("密码不能为空")

    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raw = raw[:_BCRYPT_MAX_BYTES]

    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码。哈希格式非法或密码错误统一返回 False，不抛异常。

    注意：不要把"salt 不匹配"和"密码错误"区分返回给前端，避免被枚举探测。
    """
    if not password or not password_hash:
        return False

    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # 库里存的不是合法 bcrypt 哈希（比如历史明文），一律视为校验失败
        return False
