-- 024: memory_ref_id
-- E2 实现: agent_memories 需要 ref_id 字段 (用于 RAG 引用追踪 + 承诺转换)
-- ALTER TABLE 兼容: 表可能已存在, 用 ADD COLUMN 即可 (SQLite)

ALTER TABLE agent_memories ADD COLUMN ref_id TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_mem_ref ON agent_memories(project_id, ref_id);
