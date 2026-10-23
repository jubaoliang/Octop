"""基础实体 Schema（D-CODE6）：用户、部门、角色、权限、审计日志、消息。

约定：
- XxxCreate  —— 新增入参，不包含 id / 时间字段
- XxxUpdate  —— 修改入参，所有字段可选（部分更新）
- XxxOut     —— 出参，从 ORM 对象序列化，**敏感字段自动脱敏**
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_serializer, field_validator

from app.schemas.common import ORMInput, ORMModel, TimestampOut
from app.utils.desensitize import desensitize_idcard, desensitize_phone


# ===========================================================================
# 部门 Dept
# ===========================================================================
class DeptBase(ORMInput):
    dept_name: str = Field(..., max_length=100, description="部门名称")
    dept_code: str = Field(..., max_length=50, description="部门编码")
    parent_id: int | None = Field(None, description="上级部门ID，顶级为 None")
    dept_level: int = Field(3, ge=1, le=9, description="层级：1分局 2业务大队 3派出所")
    region_code: str | None = Field(None, max_length=20, description="行政区划代码")
    address: str | None = Field(None, max_length=255, description="办公地址")
    leader_name: str | None = Field(None, max_length=50, description="负责人")
    leader_phone: str | None = Field(None, max_length=20, description="负责人电话")
    sort_no: int = Field(0, description="排序号")
    status: int = Field(1, description="状态：1启用 0停用")
    remark: str | None = Field(None, max_length=500, description="备注")


class DeptCreate(DeptBase):
    """新增部门。"""


class DeptUpdate(ORMInput):
    """修改部门（全部字段可选）。"""

    dept_name: str | None = Field(None, max_length=100)
    dept_code: str | None = Field(None, max_length=50)
    parent_id: int | None = None
    dept_level: int | None = Field(None, ge=1, le=9)
    region_code: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=255)
    leader_name: str | None = Field(None, max_length=50)
    leader_phone: str | None = Field(None, max_length=20)
    sort_no: int | None = None
    status: int | None = None
    remark: str | None = Field(None, max_length=500)


class DeptOut(TimestampOut):
    """部门出参。"""

    id: int
    dept_name: str
    dept_code: str
    parent_id: int | None = None
    dept_level: int = 3
    region_code: str | None = None
    address: str | None = None
    leader_name: str | None = None
    leader_phone: str | None = None
    sort_no: int = 0
    status: int = 1
    remark: str | None = None
    is_deleted: int = 0

    @field_serializer("leader_phone")
    def _mask_leader_phone(self, v: str | None) -> str | None:
        return desensitize_phone(v)


class DeptTreeOut(DeptOut):
    """部门树出参（递归子节点）。"""

    children: list["DeptTreeOut"] = Field(default_factory=list)


# ===========================================================================
# 警员 UserPolice
# ===========================================================================
class UserPoliceBase(ORMInput):
    police_no: str = Field(..., min_length=2, max_length=32, description="警号（登录账号）")
    real_name: str = Field(..., min_length=1, max_length=50, description="真实姓名")
    dept_id: int = Field(..., description="所属派出所/部门ID")
    phone: str | None = Field(None, max_length=20, description="手机号")
    id_card: str | None = Field(None, max_length=32, description="身份证号")
    gender: int | None = Field(None, ge=0, le=2, description="性别：1男 2女 0未知")
    avatar_url: str | None = Field(None, max_length=255)
    rank_name: str | None = Field(None, max_length=50, description="警衔")
    post_name: str | None = Field(None, max_length=50, description="职务")
    status: int = Field(1, description="状态：1正常 0停用 2待审核")

    @field_validator("police_no")
    @classmethod
    def _check_police_no(cls, v: str) -> str:
        if not v.replace("-", "").isalnum():
            raise ValueError("警号只能包含字母、数字和短横线")
        return v


class UserPoliceCreate(UserPoliceBase):
    """新增警员。密码明文只在入参出现，落库前必须哈希。"""

    password: str = Field(..., min_length=8, max_length=64, description="登录密码（明文，需哈希后存储）")
    role_codes: list[str] = Field(default_factory=list, description="初始角色编码列表")


class UserPoliceUpdate(ORMInput):
    """修改警员。police_no 不允许改（警号是追责依据）。"""

    real_name: str | None = Field(None, min_length=1, max_length=50)
    dept_id: int | None = None
    phone: str | None = Field(None, max_length=20)
    id_card: str | None = Field(None, max_length=32)
    gender: int | None = Field(None, ge=0, le=2)
    avatar_url: str | None = Field(None, max_length=255)
    rank_name: str | None = Field(None, max_length=50)
    post_name: str | None = Field(None, max_length=50)
    status: int | None = None


class UserPoliceOut(TimestampOut):
    """警员出参。手机号、身份证号默认打码 —— 需要原值请走专用授权接口。"""

    id: int
    police_no: str
    real_name: str
    dept_id: int
    dept_name: str | None = Field(None, description="所属部门名称（联表带出，可选）")
    phone: str | None = None
    id_card: str | None = None
    gender: int | None = None
    avatar_url: str | None = None
    rank_name: str | None = None
    post_name: str | None = None
    status: int = 1
    last_login_time: datetime | None = None
    last_login_ip: str | None = None

    @field_serializer("phone")
    def _mask_phone(self, v: str | None) -> str | None:
        return desensitize_phone(v)

    @field_serializer("id_card")
    def _mask_idcard(self, v: str | None) -> str | None:
        return desensitize_idcard(v)


# ===========================================================================
# 角色 Role
# ===========================================================================
class RoleBase(ORMInput):
    role_code: str = Field(..., max_length=50, description="角色编码，如 admin/police/auditor")
    role_name: str = Field(..., max_length=50, description="角色名称")
    data_scope: str = Field("DEPT", description="数据范围：ALL全局 DEPT本部门 SELF仅本人")
    description: str | None = Field(None, max_length=255)
    status: int = Field(1, description="状态：1启用 0停用")

    @field_validator("data_scope")
    @classmethod
    def _check_scope(cls, v: str) -> str:
        v = v.upper()
        if v not in {"ALL", "DEPT", "SELF"}:
            raise ValueError("data_scope 只能是 ALL / DEPT / SELF")
        return v


class RoleCreate(RoleBase):
    """新增角色，可同时绑定权限点。"""

    perm_codes: list[str] = Field(default_factory=list, description="权限编码列表")


class RoleUpdate(ORMInput):
    role_name: str | None = Field(None, max_length=50)
    data_scope: str | None = None
    description: str | None = Field(None, max_length=255)
    status: int | None = None


class RoleOut(TimestampOut):
    id: int
    role_code: str
    role_name: str
    data_scope: str = "DEPT"
    description: str | None = None
    status: int = 1
    perm_codes: list[str] = Field(default_factory=list, description="拥有的权限编码")


class RolePermAssign(ORMInput):
    """给角色重新分配权限（全量覆盖）。"""

    perm_codes: list[str] = Field(default_factory=list, description="权限编码列表，传空表示清空")


class UserRoleAssign(ORMInput):
    """给用户重新分配角色（全量覆盖）。"""

    role_codes: list[str] = Field(default_factory=list)


# ===========================================================================
# 审计日志 OperationLog
# ===========================================================================
class OperationLogCreate(ORMInput):
    """手工写日志（一般用 write_operation_log，此处供接口层批量导入用）。"""

    user_id: int | None = None
    police_no: str | None = Field(None, max_length=32)
    dept_id: int | None = None
    op_type: str = Field(..., max_length=50, description="操作类型")
    target_type: str | None = Field(None, max_length=50, description="操作对象类型")
    target_id: int | None = None
    detail: str | None = Field(None, description="操作详情")
    client_ip: str | None = Field(None, max_length=64)
    is_sensitive: int = Field(0, ge=0, le=1)


class OperationLogOut(ORMModel):
    id: int
    user_id: int | None = None
    police_no: str | None = None
    dept_id: int | None = None
    op_type: str
    target_type: str | None = None
    target_id: int | None = None
    detail: str | None = None
    client_ip: str | None = None
    is_sensitive: int = 0
    create_time: datetime


class OperationLogQuery(ORMInput):
    """审计日志查询条件。"""

    user_id: int | None = None
    dept_id: int | None = None
    op_type: str | None = None
    target_type: str | None = None
    target_id: int | None = None
    is_sensitive: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


# ===========================================================================
# 消息 Message
# ===========================================================================
class MessageCreate(ORMInput):
    title: str = Field(..., max_length=200, description="消息标题")
    content: str | None = Field(None, description="消息正文")
    msg_type: str = Field("SYSTEM", description="类型：SYSTEM/AUDIT/NOTICE")
    biz_type: str | None = Field(None, max_length=50)
    biz_id: int | None = None
    sender_id: int | None = None
    receiver_id: int = Field(..., description="接收人ID")
    receiver_dept_id: int | None = None


class MessageOut(TimestampOut):
    id: int
    title: str
    content: str | None = None
    msg_type: str = "SYSTEM"
    biz_type: str | None = None
    biz_id: int | None = None
    sender_id: int | None = None
    receiver_id: int
    receiver_dept_id: int | None = None
    is_read: int = 0
    read_time: datetime | None = None
