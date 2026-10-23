"""业务模型（占位版）：agent / template / audit_task / kb_doc 等。

⚠️ 重要说明
-----------
B 的字段清单还没最终交付，这里的字段是**按当前需求推定的最小可用集合**，
目的是让 D-CODE9（示例路由）、E 的测试脚手架现在就能跑通。

拿到 B 的字段清单后，只需同步两处即可，不动任何权限/审计代码：
1. 本文件的列定义
2. `sql/02_biz_tables.sql` 的建表语句

所有业务表都必须带 `dept_id` 列 —— 这是行级数据隔离的硬性前提。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, SoftDeleteMixin, TimestampMixin

# PostgreSQL 用 JSONB（可索引），SQLite 退化为 JSON
JsonType = JSON().with_variant(JSONB, "postgresql")


# ---------------------------------------------------------------------------
# agent 智能体表
# ---------------------------------------------------------------------------
class Agent(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """智能体。dept_id 决定归属派出所，是越权校验的核心字段。"""

    __tablename__ = "agent"
    __table_args__ = (
        Index("idx_agent_dept_status", "dept_id", "status"),
        # 编码在「未删除」范围内唯一：删掉之后可以复用同一个编码
        Index(
            "uk_agent_code_alive",
            "agent_code",
            unique=True,
            postgresql_where=text("is_deleted = 0"),
            sqlite_where=text("is_deleted = 0"),
        ),
        CheckConstraint(
            "status IN ('DRAFT','REVIEWING','PUBLISHED','OFFLINE')",
            name="ck_agent_status",
        ),
        {"comment": "智能体表"},
    )

    agent_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="智能体编码（唯一）")
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="智能体名称")
    agent_type: Mapped[str] = mapped_column(
        String(50), default="CHAT", comment="类型：CHAT对话 WORKFLOW流程 RAG知识库"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="简介")
    model_code: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="所用大模型编码")
    model_params: Mapped[dict | None] = mapped_column(
        JsonType, nullable=True, comment="模型参数（温度、max_tokens等）"
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="系统提示词")
    status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", comment="状态：DRAFT草稿 REVIEWING审核中 PUBLISHED已发布 OFFLINE已下线"
    )
    current_version: Mapped[int] = mapped_column(Integer, default=0, comment="当前版本号")
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=False, comment="归属部门ID（数据隔离依据）"
    )
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="创建人ID"
    )
    publish_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="发布时间"
    )


# ---------------------------------------------------------------------------
# agent_version 智能体版本表
# ---------------------------------------------------------------------------
class AgentVersion(Base, PKMixin, TimestampMixin):
    """智能体版本快照。发布后不可改，只能新增版本。"""

    __tablename__ = "agent_version"
    __table_args__ = (
        UniqueConstraint("agent_id", "version_no", name="uk_agent_ver"),
        Index("idx_agent_ver_agent", "agent_id", "version_no"),
        {"comment": "智能体版本表"},
    )

    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent.id", ondelete="CASCADE"), nullable=False, comment="智能体ID"
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号，从1递增")
    config_snapshot: Mapped[dict | None] = mapped_column(
        JsonType, nullable=True, comment="版本配置快照（提示词、模型参数等）"
    )
    change_log: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更说明")
    dept_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="归属部门ID（从 agent 继承，禁止为空）"
    )
    creator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="创建人ID")


# ---------------------------------------------------------------------------
# template 模板表
# ---------------------------------------------------------------------------
class Template(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """模板（公文/笔录/报告等）。"""

    __tablename__ = "template"
    __table_args__ = (
        Index("idx_template_dept", "dept_id"),
        CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','OFFLINE')", name="ck_template_status"
        ),
        {"comment": "模板表"},
    )

    template_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="模板编码")
    template_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="模板名称")
    template_type: Mapped[str] = mapped_column(
        String(50), default="DOC", comment="类型：DOC文档 TABLE表格 FORM表单"
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="模板内容")
    status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", comment="状态：DRAFT PUBLISHED OFFLINE"
    )
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=False, comment="归属部门ID"
    )
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="创建人ID")


# ---------------------------------------------------------------------------
# audit_task 审核工单表
# ---------------------------------------------------------------------------
class AuditTask(Base, PKMixin, TimestampMixin):
    """审核工单：智能体/模板发布前的人工审核流程。"""

    __tablename__ = "audit_task"
    __table_args__ = (
        Index("idx_audit_task_status", "status", "dept_id"),
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED')", name="ck_audit_task_status"
        ),
        {"comment": "审核工单表"},
    )

    task_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="工单号")
    biz_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="业务类型：agent/template/kb_doc"
    )
    biz_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="业务对象ID")
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="工单标题")
    submitter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="提交人ID")
    auditor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="审核人ID")
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", comment="状态：PENDING待审核 APPROVED通过 REJECTED驳回"
    )
    audit_opinion: Mapped[str | None] = mapped_column(Text, nullable=True, comment="审核意见")
    audit_time: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="审核时间"
    )
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=False, comment="归属部门ID"
    )


# ---------------------------------------------------------------------------
# kb_doc 知识库文档表
# ---------------------------------------------------------------------------
class KbDoc(Base, PKMixin, TimestampMixin, SoftDeleteMixin):
    """知识库文档。"""

    __tablename__ = "kb_doc"
    __table_args__ = (
        Index("idx_kbdoc_dept", "dept_id", "status"),
        CheckConstraint(
            "status IN ('PENDING','PARSING','READY','FAILED')", name="ck_kb_doc_status"
        ),
        {"comment": "知识库文档表"},
    )

    doc_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="文档名称")
    doc_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="文档类型：PDF/DOCX/TXT/MD")
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="文件存储地址")
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="文件大小（字节）")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, comment="切片数量")
    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", comment="状态：PENDING待解析 PARSING解析中 READY就绪 FAILED失败"
    )
    dept_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dept.id"), nullable=False, comment="归属部门ID"
    )
    uploader_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="上传人ID")


# ---------------------------------------------------------------------------
# kb_chunk 知识库分片表
# ---------------------------------------------------------------------------
class KbChunk(Base, PKMixin, TimestampMixin):
    """知识库切片。向量列（embedding）待 B 确认向量库方案后再加。"""

    __tablename__ = "kb_chunk"
    __table_args__ = (
        Index("idx_kbchunk_doc", "doc_id", "chunk_index"),
        {"comment": "知识库分片表"},
    )

    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("kb_doc.id", ondelete="CASCADE"), nullable=False, comment="所属文档ID"
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="分片序号，从0开始")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分片文本内容")
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="token数量")
    vector_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="向量库中的ID，用于召回"
    )
    dept_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="归属部门ID（从 kb_doc 继承，禁止为空）"
    )
