-- ============================================================================
-- 民警工作台 · 基础数据表建表脚本（D-CODE1）
-- 数据库：PostgreSQL 12+
-- 执行：psql -U postgres -d police_workbench -f 01_base_tables.sql
-- 说明：
--   1. 只建基础/权限/日志/消息表，不含 agent、template 等业务表（见 02）
--   2. 主键统一 BIGSERIAL，时间字段统一 create_time / update_time
--   3. update_time 由触发器自动维护，应用层不传也不会漏
--   4. 脚本可重复执行（IF NOT EXISTS + ON CONFLICT）
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 公共：自动更新 update_time 的触发器函数
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trg_set_update_time()
RETURNS TRIGGER AS $$
BEGIN
    NEW.update_time = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION trg_set_update_time() IS '通用触发器：更新记录时自动刷新 update_time';


-- ===========================================================================
-- 1. dept 派出所/部门表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS dept (
    id            BIGSERIAL    PRIMARY KEY,
    dept_name     VARCHAR(100) NOT NULL,
    dept_code     VARCHAR(50)  NOT NULL,
    parent_id     BIGINT       NULL,
    dept_level    SMALLINT     NOT NULL DEFAULT 3,
    region_code   VARCHAR(20)  NULL,
    address       VARCHAR(255) NULL,
    leader_name   VARCHAR(50)  NULL,
    leader_phone  VARCHAR(20)  NULL,
    sort_no       INTEGER      NOT NULL DEFAULT 0,
    status        SMALLINT     NOT NULL DEFAULT 1,
    remark        VARCHAR(500) NULL,
    create_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted    SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT uk_dept_code UNIQUE (dept_code),
    CONSTRAINT fk_dept_parent FOREIGN KEY (parent_id) REFERENCES dept (id)
);

COMMENT ON TABLE  dept               IS '派出所/部门表';
COMMENT ON COLUMN dept.id            IS '主键ID';
COMMENT ON COLUMN dept.dept_name     IS '部门名称';
COMMENT ON COLUMN dept.dept_code     IS '部门编码（派出所唯一标识）';
COMMENT ON COLUMN dept.parent_id     IS '上级部门ID，顶级为NULL';
COMMENT ON COLUMN dept.dept_level    IS '层级：1分局 2业务大队 3派出所';
COMMENT ON COLUMN dept.region_code   IS '行政区划代码';
COMMENT ON COLUMN dept.address       IS '办公地址';
COMMENT ON COLUMN dept.leader_name   IS '负责人姓名';
COMMENT ON COLUMN dept.leader_phone  IS '负责人电话（展示需脱敏）';
COMMENT ON COLUMN dept.sort_no       IS '排序号，越小越靠前';
COMMENT ON COLUMN dept.status        IS '状态：1启用 0停用';
COMMENT ON COLUMN dept.remark        IS '备注';
COMMENT ON COLUMN dept.create_time   IS '创建时间';
COMMENT ON COLUMN dept.update_time   IS '更新时间';
COMMENT ON COLUMN dept.is_deleted    IS '软删除标记：0正常 1已删除';

CREATE INDEX IF NOT EXISTS idx_dept_parent ON dept (parent_id);
CREATE INDEX IF NOT EXISTS idx_dept_status ON dept (status, is_deleted);


-- ===========================================================================
-- 2. user_police 警员用户表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS user_police (
    id              BIGSERIAL    PRIMARY KEY,
    police_no       VARCHAR(32)  NOT NULL,
    real_name       VARCHAR(50)  NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    dept_id         BIGINT       NOT NULL,
    phone           VARCHAR(20)  NULL,
    id_card         VARCHAR(32)  NULL,
    gender          SMALLINT     NULL DEFAULT 0,
    avatar_url      VARCHAR(255) NULL,
    rank_name       VARCHAR(50)  NULL,
    post_name       VARCHAR(50)  NULL,
    status          SMALLINT     NOT NULL DEFAULT 1,
    last_login_time TIMESTAMP    NULL,
    last_login_ip   VARCHAR(64)  NULL,
    create_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted      SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT uk_user_police_no UNIQUE (police_no),
    CONSTRAINT fk_user_police_dept FOREIGN KEY (dept_id) REFERENCES dept (id)
);

COMMENT ON TABLE  user_police                 IS '警员用户表';
COMMENT ON COLUMN user_police.id              IS '主键ID';
COMMENT ON COLUMN user_police.police_no       IS '警号（登录账号）';
COMMENT ON COLUMN user_police.real_name       IS '真实姓名';
COMMENT ON COLUMN user_police.password_hash   IS '密码哈希（bcrypt），禁止存明文';
COMMENT ON COLUMN user_police.dept_id         IS '所属派出所/部门ID（行级数据隔离依据）';
COMMENT ON COLUMN user_police.phone           IS '手机号（敏感，展示需脱敏）';
COMMENT ON COLUMN user_police.id_card         IS '身份证号（敏感，展示需脱敏）';
COMMENT ON COLUMN user_police.gender          IS '性别：1男 2女 0未知';
COMMENT ON COLUMN user_police.avatar_url      IS '头像地址';
COMMENT ON COLUMN user_police.rank_name       IS '警衔';
COMMENT ON COLUMN user_police.post_name       IS '职务';
COMMENT ON COLUMN user_police.status          IS '状态：1正常 0停用 2待审核';
COMMENT ON COLUMN user_police.last_login_time IS '最后登录时间';
COMMENT ON COLUMN user_police.last_login_ip   IS '最后登录IP';
COMMENT ON COLUMN user_police.create_time     IS '创建时间';
COMMENT ON COLUMN user_police.update_time     IS '更新时间';
COMMENT ON COLUMN user_police.is_deleted      IS '软删除标记：0正常 1已删除';

CREATE INDEX IF NOT EXISTS idx_user_police_dept   ON user_police (dept_id);
CREATE INDEX IF NOT EXISTS idx_user_police_status ON user_police (status, is_deleted);


-- ===========================================================================
-- 3. role 角色表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS "role" (
    id          BIGSERIAL    PRIMARY KEY,
    role_code   VARCHAR(50)  NOT NULL,
    role_name   VARCHAR(50)  NOT NULL,
    data_scope  VARCHAR(20)  NOT NULL DEFAULT 'DEPT',
    description VARCHAR(255) NULL,
    status      SMALLINT     NOT NULL DEFAULT 1,
    create_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_deleted  SMALLINT     NOT NULL DEFAULT 0,
    CONSTRAINT uk_role_code UNIQUE (role_code),
    CONSTRAINT ck_role_data_scope CHECK (data_scope IN ('ALL', 'DEPT', 'SELF'))
);

COMMENT ON TABLE  "role"              IS '角色表';
COMMENT ON COLUMN "role".id           IS '主键ID';
COMMENT ON COLUMN "role".role_code    IS '角色编码，如admin/police/auditor';
COMMENT ON COLUMN "role".role_name    IS '角色名称';
COMMENT ON COLUMN "role".data_scope   IS '数据范围：ALL全局 DEPT本部门 SELF仅本人';
COMMENT ON COLUMN "role".description  IS '角色描述';
COMMENT ON COLUMN "role".status       IS '状态：1启用 0停用';
COMMENT ON COLUMN "role".create_time  IS '创建时间';
COMMENT ON COLUMN "role".update_time  IS '更新时间';
COMMENT ON COLUMN "role".is_deleted   IS '软删除标记：0正常 1已删除';


-- ===========================================================================
-- 4. user_role 用户角色关联表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS user_role (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT    NOT NULL,
    role_id     BIGINT    NOT NULL,
    create_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_user_role UNIQUE (user_id, role_id),
    CONSTRAINT fk_user_role_user FOREIGN KEY (user_id) REFERENCES user_police (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_role_role FOREIGN KEY (role_id) REFERENCES "role" (id) ON DELETE CASCADE
);

COMMENT ON TABLE  user_role             IS '用户角色关联表';
COMMENT ON COLUMN user_role.id          IS '主键ID';
COMMENT ON COLUMN user_role.user_id     IS '用户ID';
COMMENT ON COLUMN user_role.role_id     IS '角色ID';
COMMENT ON COLUMN user_role.create_time IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_user_role_user ON user_role (user_id);
CREATE INDEX IF NOT EXISTS idx_user_role_role ON user_role (role_id);


-- ===========================================================================
-- 5. role_perm 角色权限关联表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS role_perm (
    id          BIGSERIAL    PRIMARY KEY,
    role_id     BIGINT       NOT NULL,
    perm_code   VARCHAR(100) NOT NULL,
    perm_name   VARCHAR(100) NULL,
    perm_type   VARCHAR(20)  NOT NULL DEFAULT 'API',
    create_time TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_role_perm UNIQUE (role_id, perm_code),
    CONSTRAINT fk_role_perm_role FOREIGN KEY (role_id) REFERENCES "role" (id) ON DELETE CASCADE
);

COMMENT ON TABLE  role_perm             IS '角色权限关联表';
COMMENT ON COLUMN role_perm.id          IS '主键ID';
COMMENT ON COLUMN role_perm.role_id     IS '角色ID';
COMMENT ON COLUMN role_perm.perm_code   IS '权限编码，如 agent:create / audit:approve';
COMMENT ON COLUMN role_perm.perm_name   IS '权限名称';
COMMENT ON COLUMN role_perm.perm_type   IS '权限类型：MENU菜单 BUTTON按钮 API接口 DATA数据';
COMMENT ON COLUMN role_perm.create_time IS '创建时间';

CREATE INDEX IF NOT EXISTS idx_role_perm_role ON role_perm (role_id);


-- ===========================================================================
-- 6. operation_log 审计日志表
-- 只增不改不删：没有 update_time / is_deleted
-- ===========================================================================
CREATE TABLE IF NOT EXISTS operation_log (
    id           BIGSERIAL    PRIMARY KEY,
    user_id      BIGINT       NULL,
    police_no    VARCHAR(32)  NULL,
    dept_id      BIGINT       NULL,
    op_type      VARCHAR(50)  NOT NULL,
    target_type  VARCHAR(50)  NULL,
    target_id    BIGINT       NULL,
    detail       TEXT         NULL,
    client_ip    VARCHAR(64)  NULL,
    is_sensitive SMALLINT     NOT NULL DEFAULT 0,
    create_time  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE  operation_log              IS '操作审计日志表（只增不改）';
COMMENT ON COLUMN operation_log.id           IS '主键ID';
COMMENT ON COLUMN operation_log.user_id      IS '操作人用户ID';
COMMENT ON COLUMN operation_log.police_no    IS '操作人警号（冗余存储，便于追责）';
COMMENT ON COLUMN operation_log.dept_id      IS '操作人所属部门ID';
COMMENT ON COLUMN operation_log.op_type      IS '操作类型：CREATE/UPDATE/DELETE/QUERY/LOGIN/AUDIT/PUBLISH';
COMMENT ON COLUMN operation_log.target_type  IS '操作对象类型，如agent/template/user';
COMMENT ON COLUMN operation_log.target_id    IS '操作对象ID';
COMMENT ON COLUMN operation_log.detail       IS '操作详情/变更内容，建议存JSON字符串';
COMMENT ON COLUMN operation_log.client_ip    IS '客户端IP';
COMMENT ON COLUMN operation_log.is_sensitive IS '是否敏感操作：0否 1是';
COMMENT ON COLUMN operation_log.create_time  IS '操作时间';

CREATE INDEX IF NOT EXISTS idx_oplog_dept_time ON operation_log (dept_id, create_time DESC);
CREATE INDEX IF NOT EXISTS idx_oplog_user      ON operation_log (user_id);
CREATE INDEX IF NOT EXISTS idx_oplog_type      ON operation_log (op_type);
CREATE INDEX IF NOT EXISTS idx_oplog_target    ON operation_log (target_type, target_id);


-- ===========================================================================
-- 7. message 消息通知表
-- ===========================================================================
CREATE TABLE IF NOT EXISTS message (
    id               BIGSERIAL    PRIMARY KEY,
    title            VARCHAR(200) NOT NULL,
    content          TEXT         NULL,
    msg_type         VARCHAR(50)  NOT NULL DEFAULT 'SYSTEM',
    biz_type         VARCHAR(50)  NULL,
    biz_id           BIGINT       NULL,
    sender_id        BIGINT       NULL,
    receiver_id      BIGINT       NOT NULL,
    receiver_dept_id BIGINT       NULL,
    is_read          SMALLINT     NOT NULL DEFAULT 0,
    read_time        TIMESTAMP    NULL,
    create_time      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE  message                  IS '消息通知表';
COMMENT ON COLUMN message.id               IS '主键ID';
COMMENT ON COLUMN message.title            IS '消息标题';
COMMENT ON COLUMN message.content          IS '消息正文';
COMMENT ON COLUMN message.msg_type         IS '消息类型：SYSTEM系统 AUDIT审核 NOTICE公告';
COMMENT ON COLUMN message.biz_type         IS '关联业务类型，如audit_task';
COMMENT ON COLUMN message.biz_id           IS '关联业务ID，便于前端点击跳转';
COMMENT ON COLUMN message.sender_id        IS '发送人ID，NULL表示系统消息';
COMMENT ON COLUMN message.receiver_id      IS '接收人ID';
COMMENT ON COLUMN message.receiver_dept_id IS '接收人部门ID';
COMMENT ON COLUMN message.is_read          IS '是否已读：0未读 1已读';
COMMENT ON COLUMN message.read_time        IS '阅读时间';
COMMENT ON COLUMN message.create_time      IS '创建时间';
COMMENT ON COLUMN message.update_time      IS '更新时间';

CREATE INDEX IF NOT EXISTS idx_message_receiver ON message (receiver_id, is_read);


-- ===========================================================================
-- 触发器：自动维护 update_time
-- ===========================================================================
DROP TRIGGER IF EXISTS trg_dept_update_time ON dept;
CREATE TRIGGER trg_dept_update_time BEFORE UPDATE ON dept
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_user_police_update_time ON user_police;
CREATE TRIGGER trg_user_police_update_time BEFORE UPDATE ON user_police
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_role_update_time ON "role";
CREATE TRIGGER trg_role_update_time BEFORE UPDATE ON "role"
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();

DROP TRIGGER IF EXISTS trg_message_update_time ON message;
CREATE TRIGGER trg_message_update_time BEFORE UPDATE ON message
    FOR EACH ROW EXECUTE FUNCTION trg_set_update_time();


-- ===========================================================================
-- 初始角色数据（幂等，可重复执行）
-- ===========================================================================
INSERT INTO "role" (role_code, role_name, data_scope, description, status)
VALUES
    ('admin',   '系统管理员', 'ALL',  '可管理全部派出所数据，跨所可见', 1),
    ('police',  '普通民警',   'DEPT', '只能查看和操作本派出所数据',     1),
    ('auditor', '审核员',     'DEPT', '负责智能体/模板/知识库审核',     1)
ON CONFLICT (role_code) DO NOTHING;

-- 基础权限点（可按需扩充）
INSERT INTO role_perm (role_id, perm_code, perm_name, perm_type)
SELECT r.id, p.code, p.name, p.type
FROM "role" r
JOIN (VALUES
    ('agent:view',    '查看智能体',   'API'),
    ('agent:create',  '创建智能体',   'API'),
    ('agent:update',  '修改智能体',   'API'),
    ('agent:delete',  '删除智能体',   'API'),
    ('agent:publish', '发布智能体',   'API'),
    ('template:view', '查看模板',     'API'),
    ('template:edit', '编辑模板',     'API'),
    ('audit:view',    '查看审核工单', 'API'),
    ('audit:approve', '审核通过/驳回','API'),
    ('kbdoc:upload',  '上传知识库文档','API'),
    ('log:view',      '查看审计日志', 'API')
) AS p(code, name, type) ON TRUE
WHERE r.role_code = 'admin'
ON CONFLICT (role_id, perm_code) DO NOTHING;

INSERT INTO role_perm (role_id, perm_code, perm_name, perm_type)
SELECT r.id, p.code, p.name, p.type
FROM "role" r
JOIN (VALUES
    ('agent:view',    '查看智能体',   'API'),
    ('agent:create',  '创建智能体',   'API'),
    ('agent:update',  '修改智能体',   'API'),
    ('template:view', '查看模板',     'API'),
    ('kbdoc:upload',  '上传知识库文档','API')
) AS p(code, name, type) ON TRUE
WHERE r.role_code = 'police'
ON CONFLICT (role_id, perm_code) DO NOTHING;

INSERT INTO role_perm (role_id, perm_code, perm_name, perm_type)
SELECT r.id, p.code, p.name, p.type
FROM "role" r
JOIN (VALUES
    ('agent:view',    '查看智能体',   'API'),
    ('audit:view',    '查看审核工单', 'API'),
    ('audit:approve', '审核通过/驳回','API'),
    ('agent:publish', '发布智能体',   'API')
) AS p(code, name, type) ON TRUE
WHERE r.role_code = 'auditor'
ON CONFLICT (role_id, perm_code) DO NOTHING;

COMMIT;

-- ============================================================================
-- 执行完可用下面的语句自查
--   SELECT table_name, obj_description(('public.'||table_name)::regclass)
--   FROM information_schema.tables WHERE table_schema='public' ORDER BY 1;
-- ============================================================================
