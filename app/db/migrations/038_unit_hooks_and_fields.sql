-- 038_unit_hooks_and_fields.sql
-- 故事单元模式 Phase 1-3：钩子重构 + 记忆/章节加字段
-- - unit_hook_map 重构为段落锚点设计
-- - agent_memory 加 unit_step + manual_locked
-- - chapters 加 source_unit_id + split_version + is_current_version

-- ============================================================
-- 1. 重构 unit_hook_map 表
-- 旧版是 plant/payoff 在同一条，新版是每条一个锚点事件
-- 策略：重命名旧表为 _legacy，建新表
-- ============================================================

ALTER TABLE unit_hook_map RENAME TO unit_hook_map_legacy;

CREATE TABLE IF NOT EXISTS unit_hook_map (
    id TEXT PRIMARY KEY,
    unit_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    hook_id TEXT NOT NULL DEFAULT '',
    hook_type TEXT NOT NULL DEFAULT 'plant',
    paragraph_id TEXT NOT NULL DEFAULT '',
    step_no INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    manual_locked INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_unit_hook_map_unit ON unit_hook_map(unit_id);
CREATE INDEX IF NOT EXISTS idx_unit_hook_map_project ON unit_hook_map(project_id);
CREATE INDEX IF NOT EXISTS idx_unit_hook_map_hook ON unit_hook_map(hook_id);
CREATE INDEX IF NOT EXISTS idx_unit_hook_map_paragraph ON unit_hook_map(paragraph_id);

-- ============================================================
-- 2. agent_memories / agent_memory 加字段
-- ============================================================

-- 新版记忆表
ALTER TABLE agent_memories ADD COLUMN unit_step INTEGER DEFAULT 0;
ALTER TABLE agent_memories ADD COLUMN manual_locked INTEGER DEFAULT 0;

-- 旧版记忆表（兼容）
ALTER TABLE agent_memory ADD COLUMN unit_step INTEGER DEFAULT 0;
ALTER TABLE agent_memory ADD COLUMN manual_locked INTEGER DEFAULT 0;

-- ============================================================
-- 3. chapters 加字段
-- ============================================================

ALTER TABLE chapters ADD COLUMN source_unit_id TEXT DEFAULT '';
ALTER TABLE chapters ADD COLUMN split_version INTEGER DEFAULT 0;
ALTER TABLE chapters ADD COLUMN is_current_version INTEGER DEFAULT 1;
