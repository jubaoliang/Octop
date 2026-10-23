"""脱敏工具测试（E-CODE1 · test_desensitize）。

纯函数，不依赖数据库，因此这里直接断言真实结果，不留占位。
"""

from __future__ import annotations

import pytest

from app.utils.desensitize import (
    desensitize_address,
    desensitize_dict,
    desensitize_idcard,
    desensitize_name,
    desensitize_phone,
)


class TestDesensitizePhone:
    """手机号脱敏。"""

    def test_standard_11_digits(self):
        assert desensitize_phone("13812348888") == "138****8888"

    def test_keeps_length(self):
        src = "13812348888"
        assert len(desensitize_phone(src)) == len(src)

    def test_none_and_empty_pass_through(self):
        assert desensitize_phone(None) is None
        assert desensitize_phone("") == ""

    def test_too_short_fully_masked(self):
        assert desensitize_phone("123") == "***"

    def test_landline(self):
        # 10 位座机（含区号）：保留前 3 后 2
        assert desensitize_phone("0571888999") == "057*****99"

    def test_11_digits_always_treated_as_mobile(self):
        # 11 位一律按手机号规则（前 3 后 4），不区分是手机还是带区号座机
        assert desensitize_phone("05718889999") == "057****9999"


class TestDesensitizeIdCard:
    """身份证号脱敏。"""

    def test_18_digits(self):
        assert desensitize_idcard("110101199003071234") == "110101********1234"

    def test_15_digits(self):
        assert desensitize_idcard("110101900307123") == "110101******123"

    def test_keeps_length(self):
        src = "110101199003071234"
        assert len(desensitize_idcard(src)) == len(src)

    def test_none(self):
        assert desensitize_idcard(None) is None


class TestMisc:
    """姓名 / 地址 / 字典批量脱敏。"""

    def test_name(self):
        assert desensitize_name("张三") == "张*"
        assert desensitize_name("欧阳修") == "欧**"
        assert desensitize_name("张") == "张"

    def test_address(self):
        # 保留前 3 个字符，其余按原长度打码（8 字 → 3 保留 + 5 个星号）
        assert desensitize_address("临江区文一路1号", keep=3) == "临江区*****"

    def test_dict_batch(self):
        result = desensitize_dict(
            {
                "police_no": "060101",
                "phone": "13812348888",
                "id_card": "110101199003071234",
            }
        )
        assert result["police_no"] == "060101"       # 警号不脱敏
        assert result["phone"] == "138****8888"
        assert result["id_card"] == "110101********1234"


# 参数化版本（E-CODE3 补全用例时可直接扩展这张表）
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("13812348888", "138****8888"),
        ("13900001111", "139****1111"),
        (None, None),
    ],
)
def test_phone_parametrized(raw, expected):
    assert desensitize_phone(raw) == expected
