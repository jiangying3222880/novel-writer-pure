-- 057: 合并记忆表 — 删除旧 agent_memory，统一用 agent_memories
-- agent_memory (单数, schema.sql:52) 与 agent_memories (复数, 迁移013) 并存
-- agent_memories 是 E2 重写版，所有调用方统一迁移

DROP TABLE IF EXISTS agent_memory;
