"""业务实体 Schema（D-CODE8 占位版）：agent / template / audit_task / kb_doc。

⚠️ 安全要点：Create 模型里**故意不包含 dept_id**。
部门归属必须由服务端从当前登录用户令牌里取，绝不能信任前端传值，
否则前端改一个 dept_id 就能往别的派出所塞数据。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import ORMInput, ORMModel, TimestampOut

AGENT_STATUS = {"DRAFT", "REVIEWING", "PUBLISHED", "OFFLINE"}


# ===========================================================================
# agent 智能体
# ===========================================================================
class AgentBase(ORMInput):
    agent_name: str = Field(..., min_length=1, max_length=100, description="智能体名称")
    agent_type: str = Field("CHAT", description="类型：CHAT对话 WORKFLOW流程 RAG知识库")
    description: str | None = Field(None, description="简介")
    model_code: str | None = Field(None, max_length=100, description="所用大模型编码")
    model_params: dict[str, Any] | None = Field(None, description="模型参数")
    system_prompt: str | None = Field(None, description="系统提示词")


class AgentCreate(AgentBase):
    """创建智能体。dept_id 由服务端注入，不接受前端传值。"""

    agent_code: str = Field(..., min_length=2, max_length=64, description="智能体编码（唯一）")

    @field_validator("agent_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not all(ch.isalnum() or ch in "-_" for ch in v):
            raise ValueError("智能体编码只能包含字母、数字、下划线和短横线")
        return v


class AgentUpdate(ORMInput):
    """修改智能体（草稿态才允许改，发布后改要新建版本）。"""

    agent_name: str | None = Field(None, min_length=1, max_length=100)
    agent_type: str | None = None
    description: str | None = None
    model_code: str | None = Field(None, max_length=100)
    model_params: dict[str, Any] | None = None
    system_prompt: str | None = None


class AgentOut(TimestampOut):
    id: int
    agent_code: str
    agent_name: str
    agent_type: str = "CHAT"
    description: str | None = None
    model_code: str | None = None
    model_params: dict[str, Any] | None = None
    system_prompt: str | None = None
    status: str = "DRAFT"
    current_version: int = 0
    dept_id: int
    owner_id: int | None = None
    publish_time: datetime | None = None
    is_deleted: int = 0


class AgentVersionOut(ORMModel):
    id: int
    agent_id: int
    version_no: int
    config_snapshot: dict[str, Any] | None = None
    change_log: str | None = None
    creator_id: int | None = None
    create_time: datetime | None = None


# ===========================================================================
# template 模板
# ===========================================================================
class TemplateCreate(ORMInput):
    template_code: str = Field(..., min_length=2, max_length=64, description="模板编码")
    template_name: str = Field(..., min_length=1, max_length=100, description="模板名称")
    template_type: str = Field("DOC", description="类型：DOC文档 TABLE表格 FORM表单")
    content: str | None = None


class TemplateOut(TimestampOut):
    id: int
    template_code: str
    template_name: str
    template_type: str = "DOC"
    content: str | None = None
    status: str = "DRAFT"
    dept_id: int
    owner_id: int | None = None
    is_deleted: int = 0


# ===========================================================================
# audit_task 审核工单
# ===========================================================================
class AuditTaskCreate(ORMInput):
    biz_type: str = Field(..., description="业务类型：agent/template/kb_doc")
    biz_id: int = Field(..., description="业务对象ID")
    title: str | None = Field(None, max_length=200, description="工单标题")


class AuditTaskAudit(ORMInput):
    """审核动作入参。"""

    approved: bool = Field(..., description="True 通过，False 驳回")
    audit_opinion: str | None = Field(None, description="审核意见（驳回时必填）")


class AuditTaskOut(TimestampOut):
    id: int
    task_no: str
    biz_type: str
    biz_id: int
    title: str | None = None
    submitter_id: int | None = None
    auditor_id: int | None = None
    status: str = "PENDING"
    audit_opinion: str | None = None
    audit_time: datetime | None = None
    dept_id: int


# ===========================================================================
# kb_doc / kb_chunk 知识库
# ===========================================================================
class KbDocCreate(ORMInput):
    doc_name: str = Field(..., min_length=1, max_length=200, description="文档名称")
    doc_type: str | None = Field(None, max_length=50, description="PDF/DOCX/TXT/MD")
    file_url: str | None = Field(None, max_length=500, description="文件存储地址")
    file_size: int | None = Field(None, ge=0, description="文件大小（字节）")


class KbDocOut(TimestampOut):
    id: int
    doc_name: str
    doc_type: str | None = None
    file_url: str | None = None
    file_size: int | None = None
    chunk_count: int = 0
    status: str = "PENDING"
    dept_id: int
    uploader_id: int | None = None
    is_deleted: int = 0


class KbChunkOut(ORMModel):
    id: int
    doc_id: int
    chunk_index: int
    content: str
    token_count: int | None = None
    vector_id: str | None = None
    dept_id: int | None = None
