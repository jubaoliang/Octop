"""令牌与密码工具测试。

JWT 部分在 test_permission.py 里通过接口验过（401/403 全链路），
这里补两个底层工具：签解码往返、密码哈希。
"""

from __future__ import annotations

import pytest

from app.core.security import (
    TokenError,
    TokenExpiredError,
    create_access_token,
    decode_access_token,
    hash_password,
    parse_bearer_token,
    verify_password,
)


class TestToken:
    def test_roundtrip(self):
        token = create_access_token(
            7, police_no="060101", dept_id=3, roles=["police"], data_scope="DEPT"
        )
        payload = decode_access_token(token)
        assert payload["sub"] == 7          # 已从字符串转回 int
        assert payload["police_no"] == "060101"
        assert payload["dept_id"] == 3
        assert payload["roles"] == ["police"]
        assert payload["data_scope"] == "DEPT"
        assert payload["jti"]                  # 每次签发唯一

    def test_expired_token(self):
        token = create_access_token(1, expires_minutes=-1)
        with pytest.raises(TokenExpiredError):
            decode_access_token(token)

    def test_garbage_token(self):
        with pytest.raises(TokenError):
            decode_access_token("abc.def.ghi")

    def test_empty_token(self):
        with pytest.raises(TokenError):
            decode_access_token("")

    def test_parse_bearer(self):
        assert parse_bearer_token("Bearer abc123") == "abc123"
        assert parse_bearer_token("bearer abc123") == "abc123"
        assert parse_bearer_token("Basic abc123") is None
        assert parse_bearer_token(None) is None
        assert parse_bearer_token("Bearer") is None


class TestPassword:
    """密码哈希。rounds 调到 4，让单测快一点（生产是 12）。"""

    def test_hash_and_verify(self):
        hashed = hash_password("Test@12345", rounds=4)
        assert hashed.startswith("$2b$")
        assert verify_password("Test@12345", hashed) is True
        assert verify_password("Test@12346", hashed) is False

    def test_salt_is_random(self):
        """同一个密码两次哈希结果不同 —— 有盐，防彩虹表。"""
        assert hash_password("same-pwd", rounds=4) != hash_password("same-pwd", rounds=4)

    def test_empty_password_rejected(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_invalid_hash_returns_false(self):
        """库里存的是明文/坏数据时，校验返回 False 而不是崩。"""
        assert verify_password("anything", "not-a-bcrypt-hash") is False
        assert verify_password("anything", "") is False

    def test_chinese_password(self):
        pwd = "警务智能体@2026"
        assert verify_password(pwd, hash_password(pwd, rounds=4)) is True

    def test_over_72_bytes_still_consistent(self):
        """bcrypt 只认前 72 字节，超长密码截断后行为必须稳定（不能有时对有时错）。"""
        long_pwd = "a" * 100
        hashed = hash_password(long_pwd, rounds=4)
        assert verify_password(long_pwd, hashed) is True
        # 前 72 字节相同即视为同一密码 —— 这是 bcrypt 的固有特性，不是 bug
        assert verify_password("a" * 72, hashed) is True
