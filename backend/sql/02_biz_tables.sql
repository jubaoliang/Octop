-- ============================================================================
-- 民警工作台 · 业务表建表脚本（D-CODE7 占位版）
-- 数据库：PostgreSQL 12+
--
-- ⚠️ 前置条件：B 的字段清单尚未最终交付。
--    本脚本的字段是按当前需求推定的最小可用集合，与 app/models/biz.py 保持一致。
--    拿到 B 的字段清单后，同步修改本文件 + app/models/biz.py 两处即可，
--    不需要动任何权限 / 审计代码。
--
-- 硬性约束（不要破坏）：
--    每张业务表都必须有 dept_id 列，且非空 —— 这是行级数据隔离的地基。
-- ============================================================================

BEGIN;

-- 复用 01 脚本里的更新时间触发器函数
CREATE OR REPLACE FUNCTION trg_set_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ===========================================================================
-- 1. agent 智能体表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS agent (
    id              BIGSERIAL    PRIMARY KEY,
    agent_code      VARCHAR(64)  NOT NULL,
    agent_name      VARCHAR(100) NOT NULL,
    agent_type      VARCHAR(50)  NOT NULL DEFAULT 'CHAT',
    description     TEXT         NULL,
    model_code      VARCHAR(100) NULL,
    model_params    JSONB        NULL,
    system_prompt   TEXT         NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'DRAFT',
    current_version INTEGER      NOT NULL DEFAULT 0,
    dept_id         BIGINT       NOT NULL,
    owner_id        BIGINT       NULL,
    publish_time    TIMESTAMP    NULL,
    create_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted      SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT fk_agent_dept FOREIGN KEY (dept_id) REFERENCES dept (id),
    CONSTRAINT ck_agent_status CHECK (status IN ('DRAFT','REVIEWING','PUBLISHED','OFFLINE'))
);

COMMENT ON TABLE  agent                 IS '智能体表';
COMMENT ON COLUMN agent.id              IS '主键ID';
COMMENT ON COLUMN agent.agent_code      IS '智能体编码（唯一）';
COMMENT ON COLUMN agent.agent_name      IS '智能体名称';
COMMENT ON COLUMN agent.agent_type      IS '类型：CHAT对话 WORKFLOW流程 RAG知识库';
COMMENT ON COLUMN agent.model_code      IS '所用大模型编码';
COMMENT ON COLUMN agent.model_params    IS '模型参数（温度、max_tokens等），JSONB';
COMMENT ON COLUMN agent.system_prompt   IS '系统提示词';
COMMENT ON COLUMN agent.status          IS '状态：DRAFT草稿 REVIEWING审核中 PUBLISHED已发布 OFFLINE已下线';
COMMENT ON COLUMN agent.current_version IS '当前版本号';
COMMENT ON COLUMN agent.dept_id         IS '归属部门ID（数据隔离依据）';
COMMENT ON COLUMN agent.owner_id        IS '创建人ID';
COMMENT ON COLUMN agent.publish_time    IS '发布时间';
COMMENT ON COLUMN agent.is_deleted      IS '软删除标记：0正常 1已删除';

CREATE INDEX IF NOT EXISTS idx_agent_dept_status ON agent (dept_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uk_agent_code_alive
    ON agent (agent_code) WHERE is_deleted = 0;


-- ===========================================================================
-- 2. agent_version 智能体版本表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS agent_version (
    id              BIGSERIAL PRIMARY KEY,
    agent_id        BIGINT    NOT NULL,
    version_no      INTEGER   NOT NULL,
    config_snapshot JSONB     NULL,
    change_log      TEXT      NULL,
    dept_id         BIGINT    NOT NULL,
    creator_id      BIGINT    NULL,
    create_time     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_agent_ver_agent FOREIGN KEY (agent_id) REFERENCES agent (id) ON DELETE CASCADE,
    CONSTRAINT uk_agent_ver UNIQUE (agent_id, version_no)
);

COMMENT ON TABLE  agent_version                 IS '智能体版本表（发布后不可变，只能新增版本）';
COMMENT ON COLUMN agent_version.id              IS '主键ID';
COMMENT ON COLUMN agent_version.agent_id        IS '智能体ID';
COMMENT ON COLUMN agent_version.version_no      IS '版本号，从1递增';
COMMENT ON COLUMN agent_version.config_snapshot IS '版本配置快照（提示词、模型参数等）';
COMMENT ON COLUMN agent_version.change_log      IS '变更说明';
COMMENT ON COLUMN agent_version.dept_id         IS '归属部门ID（必须由程序从 agent 继承，禁止为空）';
COMMENT ON COLUMN agent_version.creator_id      IS '创建人ID';

CREATE INDEX IF NOT EXISTS idx_agent_ver_agent ON agent_version (agent_id, version_no);


-- ===========================================================================
-- 3. template 模板表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS template (
    id            BIGSERIAL    PRIMARY KEY,
    template_code VARCHAR(64)  NOT NULL,
    template_name VARCHAR(100) NOT NULL,
    template_type VARCHAR(50)  NOT NULL DEFAULT 'DOC',
    content       TEXT         NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'DRAFT',
    dept_id       BIGINT       NOT NULL,
    owner_id      BIGINT       NULL,
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted    SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT fk_template_dept FOREIGN KEY (dept_id) REFERENCES dept (id),
    CONSTRAINT ck_template_status CHECK (status IN ('DRAFT','PUBLISHED','OFFLINE'))
);

COMMENT ON TABLE  template               IS '模板表';
COMMENT ON COLUMN template.id            IS '主键ID';
COMMENT ON COLUMN template.template_code IS '模板编码';
COMMENT ON COLUMN template.template_name IS '模板名称';
COMMENT ON COLUMN template.template_type IS '类型：DOC文档 TABLE表格 FORM表单';
COMMENT ON COLUMN template.content       IS '模板内容';
COMMENT ON COLUMN template.status        IS '状态：DRAFT PUBLISHED OFFLINE';
COMMENT ON COLUMN template.dept_id       IS '归属部门ID（数据隔离依据）';
COMMENT ON COLUMN template.owner_id      IS '创建人ID';
COMMENT ON COLUMN template.is_deleted    IS '软删除标记：0正常 1已删除';

CREATE INDEX IF NOT EXISTS idx_template_dept ON template (dept_id);


-- ===========================================================================
-- 4. audit_task 审核工单表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS audit_task (
    id            BIGSERIAL    PRIMARY KEY,
    task_no       VARCHAR(64)  NOT NULL,
    biz_type      VARCHAR(50)  NOT NULL,
    biz_id        BIGINT       NOT NULL,
    title         VARCHAR(200) NULL,
    submitter_id  BIGINT       NULL,
    auditor_id    BIGINT       NULL,
    status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    audit_opinion TEXT         NULL,
    audit_time    TIMESTAMP    NULL,
    dept_id       BIGINT       NOT NULL,
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_audit_task_dept FOREIGN KEY (dept_id) REFERENCES dept (id),
    CONSTRAINT ck_audit_task_status CHECK (status IN ('PENDING','APPROVED','REJECTED'))
);

COMMENT ON TABLE  audit_task               IS '审核工单表';
COMMENT ON COLUMN audit_task.id            IS '主键ID';
COMMENT ON COLUMN audit_task.task_no       IS '工单号';
COMMENT ON COLUMN audit_task.biz_type      IS '业务类型：agent/template/kb_doc';
COMMENT ON COLUMN audit_task.biz_id        IS '业务对象ID';
COMMENT ON COLUMN audit_task.title         IS '工单标题';
COMMENT ON COLUMN audit_task.submitter_id  IS '提交人ID';
COMMENT ON COLUMN audit_task.auditor_id    IS '审核人ID';
COMMENT ON COLUMN audit_task.status        IS '状态：PENDING待审核 APPROVED通过 REJECTED驳回';
COMMENT ON COLUMN audit_task.audit_opinion IS '审核意见';
COMMENT ON COLUMN audit_task.audit_time    IS '审核时间';
COMMENT ON COLUMN audit_task.dept_id       IS '归属部门ID（数据隔离依据）';

CREATE INDEX IF NOT EXISTS idx_audit_task_status ON audit_task (status, dept_id);


-- ===========================================================================
-- 5. kb_doc 知识库文档表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS kb_doc (
    id          BIGSERIAL    PRIMARY KEY,
    doc_name    VARCHAR(200) NOT NULL,
    doc_type    VARCHAR(50)  NULL,
    file_url    VARCHAR(500) NULL,
    file_size   BIGINT       NULL,
    chunk_count INTEGER      NOT NULL DEFAULT 0,
    status      VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    dept_id     BIGINT       NOT NULL,
    uploader_id BIGINT       NULL,
    create_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted  SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT fk_kb_doc_dept FOREIGN KEY (dept_id) REFERENCES dept (id),
    CONSTRAINT ck_kb_doc_status CHECK (status IN ('PENDING','PARSING','READY','FAILED'))
);

COMMENT ON TABLE  kb_doc             IS '知识库文档表';
COMMENT ON COLUMN kb_doc.id          IS '主键ID';
COMMENT ON COLUMN kb_doc.doc_name    IS '文档名称';
COMMENT ON COLUMN kb_doc.doc_type    IS '文档类型：PDF/DOCX/TXT/MD';
COMMENT ON COLUMN kb_doc.file_url    IS '文件存储地址';
COMMENT ON COLUMN kb_doc.file_size   IS '文件大小（字节）';
COMMENT ON COLUMN kb_doc.chunk_count IS '切片数量';
COMMENT ON COLUMN kb_doc.status      IS '状态：PENDING待解析 PARSING解析中 READY就绪 FAILED失败';
COMMENT ON COLUMN kb_doc.dept_id     IS '归属部门ID（数据隔离依据）';
COMMENT ON COLUMN kb_doc.uploader_id IS '上传人ID';
COMMENT ON COLUMN kb_doc.is_deleted  IS '软删除标记：0正常 1已删除';

CREATE INDEX IF NOT EXISTS idx_kbdoc_dept ON kb_doc (dept_id, status);


-- ===========================================================================
-- 6. kb_chunk 知识库分片表
--    embedding 向量列待向量库方案确定后再加（pgvector / 外部向量库二选一）
-- ===========================================================================
CREATE TABLE IF NOT EXISTS kb_chunk (
    id          BIGSERIAL PRIMARY KEY,
    doc_id      BIGINT    NOT NULL,
    chunk_index INTEGER   NOT NULL,
    content     TEXT      NOT NULL,
    token_count INTEGER   NULL,
    vector_id   VARCHAR(64) NULL,
    dept_id     BIGINT    NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_kb_chunk_doc FOREIGN KEY (doc_id) REFERENCES kb_doc (id) ON DELETE CASCADE
);

COMMENT ON TABLE  kb_chunk             IS '知识库分片表';
COMMENT ON COLUMN kb_chunk.id          IS '主键ID';
COMMENT ON COLUMN kb_chunk.doc_id      IS '所属文档ID';
COMMENT ON COLUMN kb_chunk.chunk_index IS '分片序号，从0开始';
COMMENT ON COLUMN kb_chunk.content     IS '分片文本内容';
COMMENT ON COLUMN kb_chunk.token_count IS 'token数量';
COMMENT ON COLUMN kb_chunk.vector_id   IS '向量库中的ID，用于召回';
COMMENT ON COLUMN kb_chunk.dept_id     IS '归属部门ID（冗余，必须由程序从 kb_doc 继承，禁止为空）';

CREATE INDEX IF NOT EXISTS idx_kbchunk_doc ON kb_chunk (doc_id, chunk_index);


-- ===========================================================================
-- 触发器
-- ===========================================================================
DROP TRIGGER IF EXISTS trg_agent_update_time ON agent;
CREATE TRIGGER trg_agent_update_time BEFORE UPDATE ON agent
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_template_update_time ON template;
CREATE TRIGGER trg_template_update_time BEFORE UPDATE ON template
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_audit_task_update_time ON audit_task;
CREATE TRIGGER trg_audit_task_update_time BEFORE UPDATE ON audit_task
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_kb_doc_update_time ON kb_doc;
CREATE TRIGGER trg_kb_doc_update_time BEFORE UPDATE ON kb_doc
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

COMMIT;
