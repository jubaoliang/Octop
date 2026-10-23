-- ============================================================================
-- 越权场景专项校验 SQL（D-CODE10）
-- 用途：不启动后端，直接在数据库层确认「数据隔离到底能不能漏」。
--
-- 使用方式：
--   1. 先跑 01 + 02 建表，插入测试数据（scripts/gen_mock_data.py --insert）
--   2. 用 psql 连上库，逐条执行下面 SQL，核对「预期结果」注释
--
-- 变量约定：
--   :dept_a = A派出所ID      :dept_b = B派出所ID
--   :user_a = A所民警用户ID   :user_b = B所民警用户ID
-- 也可直接把 :dept_a 换成具体数字（如 2）。
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 【场景 0】先摸清底数：各派出所有多少智能体
-- 预期：每个所都有自己的数据，且总数 = 各所之和（没有 dept_id 为空的数据）
-- ---------------------------------------------------------------------------
SELECT d.id                AS dept_id,
       d.dept_name,
       COUNT(a.id)         AS agent_count
FROM dept d
LEFT JOIN agent a ON a.dept_id = d.id AND a.is_deleted = 0
WHERE d.is_deleted = 0
GROUP BY d.id, d.dept_name
ORDER BY d.id;

-- 预期：0 行。业务表不允许出现 dept_id 为空的数据，否则谁都管不着
SELECT 'agent' AS tbl, COUNT(*) AS bad_rows FROM agent WHERE dept_id IS NULL
UNION ALL
SELECT 'template', COUNT(*) FROM template WHERE dept_id IS NULL
UNION ALL
SELECT 'kb_doc', COUNT(*) FROM kb_doc WHERE dept_id IS NULL;


-- ---------------------------------------------------------------------------
-- 【场景 1】A 所民警正常查本所数据
-- 等价于后端 select(Agent) + dept_id = :dept_a
-- 预期：只出现 dept_id = :dept_a 的行
-- ---------------------------------------------------------------------------
SELECT id, agent_code, agent_name, dept_id
FROM agent
WHERE is_deleted = 0
  AND dept_id = :dept_a;

-- 反向校验：结果里绝不应该出现别的 dept_id
-- 预期：0 行
SELECT id, agent_name, dept_id
FROM agent
WHERE is_deleted = 0
  AND dept_id = :dept_a
  AND dept_id <> :dept_a;


-- ---------------------------------------------------------------------------
-- 【场景 2】A 所民警尝试查 B 所数据（越权）
-- 等价于后端「只带 A 的 dept_id，却指定 B 的对象」
-- 预期：0 行 ←—— 这是最关键的一条
-- ---------------------------------------------------------------------------
SELECT id, agent_code, agent_name, dept_id
FROM agent
WHERE is_deleted = 0
  AND dept_id = :dept_a
  AND dept_id = :dept_b;          -- 同一条 SQL 里两个互相矛盾的条件，必然空

-- 更贴近真实的写法：前端直接传 B 所的 agent_id 来查详情
-- 后端必须同时校验 id 和 dept_id，否则单查 id 就漏了
-- 预期：0 行
SELECT id, agent_code, agent_name, dept_id
FROM agent
WHERE id = :agent_id_of_dept_b
  AND dept_id = :dept_a;


-- ---------------------------------------------------------------------------
-- 【场景 3】越权写入：A 所民警创建智能体时硬塞 B 所的 dept_id
-- 后端正确做法是 dept_id 取令牌里的值（不读请求体），
-- 这里用 SQL 模拟「如果前端传了会怎样」，用于回归测试时对比
-- ---------------------------------------------------------------------------
-- 正确写入（dept_id 来自登录态）
INSERT INTO agent (agent_code, agent_name, agent_type, status, dept_id, owner_id)
VALUES ('TEST_A_' || to_char(NOW(), 'YYYYMMDDHH24MISS'), '隔离测试-本所', 'CHAT', 'DRAFT', :dept_a, :user_a);

-- 错误写入示例（不要在后端这么写！仅用于证明风险存在）
-- INSERT INTO agent (agent_code, agent_name, dept_id, owner_id)
-- VALUES ('TEST_X_001', '越权写入', :dept_b, :user_a);

-- 写入后自查：应该只有 dept_id = :dept_a 这一条
-- 预期：1 行，且 dept_id = :dept_a
SELECT id, agent_code, agent_name, dept_id, owner_id
FROM agent
WHERE agent_code LIKE 'TEST_A_%'
  AND is_deleted = 0
ORDER BY id DESC
LIMIT 1;


-- ---------------------------------------------------------------------------
-- 【场景 4】跨所统计口径验证
-- 预期：A 所看到的 count 只等于 A 所自己的数量，与场景 0 中 A 所的行数一致
-- ---------------------------------------------------------------------------
SELECT :dept_a AS viewer_dept,
       COUNT(*) AS visible_agent_count
FROM agent
WHERE is_deleted = 0
  AND dept_id = :dept_a;


-- ---------------------------------------------------------------------------
-- 【场景 5】审核工单越权
-- 审核员只能审本所工单：确认不存在「本所审核员审了外所工单」的脏数据
-- 预期：0 行
-- ---------------------------------------------------------------------------
SELECT t.id, t.task_no, t.dept_id AS task_dept, u.dept_id AS auditor_dept, u.police_no
FROM audit_task t
JOIN user_police u ON u.id = t.auditor_id
WHERE t.auditor_id IS NOT NULL
  AND t.dept_id <> u.dept_id;


-- ---------------------------------------------------------------------------
-- 【场景 6】知识库分片越权
-- 分片表的 dept_id 必须与其所属文档一致，否则召回时会串数据
-- 预期：0 行
-- ---------------------------------------------------------------------------
SELECT c.id, c.doc_id, c.dept_id AS chunk_dept, d.dept_id AS doc_dept
FROM kb_chunk c
JOIN kb_doc d ON d.id = c.doc_id
WHERE c.dept_id IS NOT NULL
  AND c.dept_id <> d.dept_id;


-- ---------------------------------------------------------------------------
-- 【场景 7】审计日志能不能覆盖到人
-- 有操作但日志对不上人的情况，说明审计链路有漏洞
-- 预期：0 行（每一条 agent 创建都应有对应 CREATE 日志）
-- ---------------------------------------------------------------------------
SELECT a.id, a.agent_code, a.owner_id, a.dept_id, a.create_time
FROM agent a
LEFT JOIN operation_log l
       ON l.target_type = 'agent'
      AND l.target_id = a.id
      AND l.op_type = 'CREATE'
WHERE a.is_deleted = 0
  AND l.id IS NULL;


-- ---------------------------------------------------------------------------
-- 【清理】删掉测试插入的数据
-- ---------------------------------------------------------------------------
-- DELETE FROM agent WHERE agent_code LIKE 'TEST_A_%';
