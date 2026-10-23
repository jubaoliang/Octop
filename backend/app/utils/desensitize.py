"""数据脱敏工具（D-CODE4）。

纯函数，零依赖，可单独拷到任何项目里用。

设计原则：
- 脱敏后长度不变（便于前端表格对齐，也不泄露原始位数以外的信息）；
- 入参可以是 None / 空串 / 异常格式，一律安全降级，不抛异常；
- 手机号、身份证号按国标长度处理，异常长度走通用规则。
"""

from __future__ import annotations


def desensitize_phone(phone: str | None) -> str | None:
    """手机号脱敏：138****8888。

    规则：
    - 11 位标准手机号 → 保留前 3 后 4，中间 4 位打码
    - 7~10 位（含区号座机）→ 保留前 3 后 2
    - 4~6 位 → 保留前 1 后 1
    - 更短或有非数字 → 全部打码（长度不变）

    Args:
        phone: 原始手机号，允许 None。

    Returns:
        脱敏后的字符串；入参为 None / 空 时原样返回。
    """
    if phone is None:
        return None
    if not isinstance(phone, str) or not phone:
        return phone

    # 保留分隔符（如 138-1234-5678），只对数字位打码
    digits = [i for i, ch in enumerate(phone) if ch.isdigit()]
    n = len(digits)
    if n < 4:
        return "*" * len(phone)

    if n >= 11:
        keep_head, keep_tail = 3, 4
    elif n >= 7:
        keep_head, keep_tail = 3, 2
    else:
        keep_head, keep_tail = 1, 1

    mask_from = digits[keep_head]
    mask_to = digits[n - keep_tail] if keep_tail else len(phone)
    chars = list(phone)
    for i in range(mask_from, mask_to):
        if chars[i].isdigit():
            chars[i] = "*"
    return "".join(chars)


def desensitize_idcard(idcard: str | None) -> str | None:
    """身份证号脱敏：110101********1234。

    规则：
    - 18 位（二代证）→ 保留前 6（地址码）后 4，中间 8 位打码
    - 15 位（一代证）→ 保留前 6 后 3，中间 6 位打码
    - 其他长度 → 保留前 1/3、后 1/3，中间打码
    - 长度不足 6 或非字符串 → 全部打码

    Args:
        idcard: 原始身份证号，允许 None。

    Returns:
        脱敏后的字符串；入参为 None / 空 时原样返回。
    """
    if idcard is None:
        return None
    if not isinstance(idcard, str) or not idcard:
        return idcard

    digits = [i for i, ch in enumerate(idcard) if ch.isalnum()]
    n = len(digits)
    if n < 6:
        return "*" * len(idcard)

    if n >= 18:
        keep_head, keep_tail = 6, 4
    elif n >= 15:
        keep_head, keep_tail = 6, 3
    else:
        keep_head, keep_tail = max(1, n // 3), max(1, n // 3)

    mask_from = digits[keep_head]
    mask_to = digits[n - keep_tail]
    chars = list(idcard)
    for i in range(mask_from, mask_to):
        if chars[i].isalnum():
            chars[i] = "*"
    return "".join(chars)


def desensitize_name(name: str | None) -> str | None:
    """姓名脱敏：张*、欧阳**。附赠工具，消息通知/日志展示常用。"""
    if not name or not isinstance(name, str):
        return name
    if len(name) == 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def desensitize_address(address: str | None, keep: int = 6) -> str | None:
    """地址脱敏：保留前 keep 个字符，其余打码（保留长度）。"""
    if not address or not isinstance(address, str):
        return address
    if len(address) <= keep:
        return address
    return address[:keep] + "*" * (len(address) - keep)


# 字段名 → 脱敏函数，业务层可直接按字段名批量处理
DESENSITIZE_RULES = {
    "phone": desensitize_phone,
    "mobile": desensitize_phone,
    "id_card": desensitize_idcard,
    "idcard": desensitize_idcard,
    "id_number": desensitize_idcard,
    "real_name": desensitize_name,
    "leader_phone": desensitize_phone,
}


def desensitize_dict(data: dict, rules: dict | None = None) -> dict:
    """按字段名规则批量脱敏一个字典（浅层），返回新字典。

    用法：
        >>> desensitize_dict(row, {"phone": desensitize_phone})
        {'name': '张三', 'phone': '138****8888'}
    """
    rules = rules or DESENSITIZE_RULES
    result = dict(data)
    for key, func in rules.items():
        if key in result and result[key] is not None:
            result[key] = func(result[key])
    return result


# ---------------------------------------------------------------------------
# 调用示例（python -m app.utils.desensitize 可直接看效果）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("手机号脱敏：")
    for s in ["13812348888", "138-1234-5678", "05718889999", "1234", ""]:
        print(f"  {s!r:20} -> {desensitize_phone(s)!r}")

    print("身份证脱敏：")
    for s in ["110101199003071234", "110101900307123", "12345"]:
        print(f"  {s!r:22} -> {desensitize_idcard(s)!r}")

    print("姓名 / 地址脱敏：")
    print(f"  张三丰 -> {desensitize_name('张三丰')!r}")
    print(f"  临江区文一路1号 -> {desensitize_address('临江区文一路1号')!r}")

    print("字典批量脱敏：")
    print(
        "  ",
        desensitize_dict(
            {"police_no": "060123", "phone": "13812348888", "id_card": "110101199003071234"}
        ),
    )
