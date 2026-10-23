"""基础数据模型：部门、警员、角色、权限、审计日志、消息（对应 sql/01_base_tables.sql）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PKMixin, SoftDeleteMixin, TimestampMixin


# ---------------------------------------------------------------------------
# 1. dept 派出所/部门表
# ---------------------------------------------------------------------------
class Dept(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """派出所 / 部门。它是数据隔离的边界：警员只能看本所数据。"""

    __tablename__ = "dept"
    __table_args__ = (
        UniqueConstraint("dept_code", name="uk_dept_code"),
        Index("idx_dept_parent", "parent_id"),
        {"comment": "派出所/部门表"},
    )

    dept_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    dept_code: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="部门编码（派出所唯一标识）"
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=True, comment="上级部门ID，顶级为NULL"
    )
    dept_level: Mapped[int] = mapped_column(
        SmallInteger, default=3, comment="层级：1分局 2业务大队 3派出所"
    )
    region_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="行政区划代码"
    )
    address: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="办公地址")
    leader_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="负责人姓名")
    leader_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="负责人电话")
    sort_no: Mapped[int] = mapped_column(Integer, default=0, comment="排序号，越小越靠前")
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="状态：1启用 0停用"
    )
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")


# ---------------------------------------------------------------------------
# 2. user_police 警员用户表
# ---------------------------------------------------------------------------
class UserPolice(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """警员账号。dept_id 决定其可访问的数据范围。"""

    __tablename__ = "user_police"
    __table_args__ = (
        UniqueConstraint("police_no", name="uk_user_police_no"),
        Index("idx_user_police_dept", "dept_id"),
        {"comment": "警员用户表"},
    )

    police_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="警号（登录账号）")
    real_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="真实姓名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=False, comment="所属派出所/部门ID"
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号（敏感，展示需脱敏）")
    id_card: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="身份证号（敏感，展示需脱敏）")
    gender: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, comment="性别：1男 2女 0未知"
    )
    avatar_url: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="头像地址")
    rank_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="警衔")
    post_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="职务")
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, comment="状态：1正常 0停用 2待审核"
    )
    last_login_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最后登录时间"
    )
    last_login_ip: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="最后登录IP"
    )

    # 只读关联，方便序列化时带出部门名；业务写入仍走 dept_id
    dept: Mapped["Dept | None"] = relationship(lazy="selectin", viewonly=True)


# ---------------------------------------------------------------------------
# 3. role 角色表
# ---------------------------------------------------------------------------
class Role(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """角色：admin 管理员 / police 普通民警 / auditor 审核员 ..."""

    __tablename__ = "role"
    __table_args__ = (
        UniqueConstraint("role_code", name="uk_role_code"),
        {"comment": "角色表"},
    )

    role_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色编码")
    role_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="角色名称")
    data_scope: Mapped[str] = mapped_column(
        String(20), default="DEPT", comment="数据范围：ALL全局 DEPT本部门 SELF仅本人"
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="角色描述")
    status: Mapped[int] = mapped_column(SmallInteger, default=1, comment="状态：1启用 0停用")


# ---------------------------------------------------------------------------
# 4. user_role 用户角色关联表
# ---------------------------------------------------------------------------
class UserRole(Base, PKMixin):
    """用户-角色多对多。只保留 create_time，关联关系不需要 update_time。"""

    __tablename__ = "user_role"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uk_user_role"),
        Index("idx_user_role_user", "user_id"),
        {"comment": "用户角色关联表"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_police.id"), nullable=False, comment="用户ID"
    )
    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("role.id"), nullable=False, comment="角色ID"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False, comment="创建时间"
    )


# ---------------------------------------------------------------------------
# 5. role_perm 角色权限关联表
# ---------------------------------------------------------------------------
class RolePerm(Base, PKMixin):
    """角色-权限点。perm_code 用「模块:动作」命名，如 agent:create。"""

    __tablename__ = "role_perm"
    __table_args__ = (
        UniqueConstraint("role_id", "perm_code", name="uk_role_perm"),
        Index("idx_role_perm_role", "role_id"),
        {"comment": "角色权限关联表"},
    )

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("role.id"), nullable=False, comment="角色ID"
    )
    perm_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="权限编码，如agent:create")
    perm_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="权限名称")
    perm_type: Mapped[str] = mapped_column(
        String(20), default="API", comment="权限类型：MENU菜单 BUTTON按钮 API接口 DATA数据"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False, comment="创建时间"
    )


# ---------------------------------------------------------------------------
# 6. operation_log 审计日志表
# ---------------------------------------------------------------------------
class OperationLog(Base, PKMixin):
    """审计日志。只增不改不删，因此没有 update_time / is_deleted。"""

    __tablename__ = "operation_log"
    __table_args__ = (
        Index("idx_oplog_dept_time", "dept_id", "create_time"),
        Index("idx_oplog_user", "user_id"),
        Index("idx_oplog_type", "op_type"),
        {"comment": "操作审计日志表"},
    )

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作人用户ID"
    )
    police_no: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="操作人警号（冗余，便于追责）"
    )
    dept_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作人所属部门ID"
    )
    op_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="操作类型，如CREATE/UPDATE/DELETE/QUERY/LOGIN"
    )
    target_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="操作对象类型，如agent/template/user"
    )
    target_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="操作对象ID"
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作详情/变更内容")
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="客户端IP")
    is_sensitive: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="是否敏感操作：0否 1是（敏感操作需重点留痕）"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), nullable=False, comment="操作时间"
    )


# ---------------------------------------------------------------------------
# 7. message 消息通知表
# ---------------------------------------------------------------------------
class Message(Base, PKMixin, TimestampMixin):
    """站内消息：审核结果通知、系统公告等。"""

    __tablename__ = "message"
    __table_args__ = (
        Index("idx_message_receiver", "receiver_id", "is_read"),
        {"comment": "消息通知表"},
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="消息标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="消息正文")
    msg_type: Mapped[str] = mapped_column(
        String(50), default="SYSTEM", comment="消息类型：SYSTEM系统 AUDIT审核 NOTICE公告"
    )
    biz_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="关联业务类型，如audit_task"
    )
    biz_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="关联业务ID，便于点击跳转"
    )
    sender_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="发送人ID，NULL表示系统消息"
    )
    receiver_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="接收人ID"
    )
    receiver_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="接收人部门ID"
    )
    is_read: Mapped[int] = mapped_column(
        SmallInteger, default=0, comment="是否已读：0未读 1已读"
    )
    read_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="阅读时间"
    )
