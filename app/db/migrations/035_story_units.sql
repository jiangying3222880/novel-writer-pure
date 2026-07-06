-- 035_story_units.sql
-- 故事单元模式：新增 story_units 表 + unit_hook_map 表
-- 现有表增加 unit_id / story_order 字段，支持单元模式的二维时间线

-- ============================================================
-- 1. 新增表：story_units（故事单元主表）
-- ============================================================

CREATE TABLE IF NOT EXISTS story_units (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    unit_type TEXT,
    story_order INTEGER NOT NULL DEFAULT 0,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'writing', 'completed', 'split')),
    synopsis TEXT,
    draft TEXT,
    word_count INTEGER DEFAULT 0,
    emotion_basis TEXT,
    entry_characters TEXT,
    entry_world TEXT,
    entry_commitments TEXT,
    exit_characters TEXT,
    exit_world TEXT,
    exit_commitments TEXT,
    unit_memories TEXT,
    target_chapter_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_story_units_project ON story_units(project_id);
CREATE INDEX IF NOT EXISTS idx_story_units_order ON story_units(project_id, story_order);

-- ============================================================
-- 2. 新增表：unit_hook_map（单元-伏笔映射表）
-- ============================================================

CREATE TABLE IF NOT EXISTS unit_hook_map (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    hook_desc TEXT,
    hook_type TEXT DEFAULT 'promise' CHECK(hook_type IN ('promise', 'active', 'fulfilled')),
    plant_unit_id TEXT,
    payoff_unit_id TEXT,
    plant_chapter_id TEXT,
    payoff_chapter_id TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_unit_hook_map_project ON unit_hook_map(project_id);

-- ============================================================
-- 3. 现有表增加 unit_id 字段（支持单元锚定）
-- ============================================================

-- agent_memories (新版记忆表)
ALTER TABLE agent_memories ADD COLUMN unit_id TEXT DEFAULT '';
ALTER TABLE agent_memories ADD COLUMN story_order INTEGER DEFAULT 0;

-- agent_memory (旧版记忆表，兼容)
ALTER TABLE agent_memory ADD COLUMN unit_id TEXT DEFAULT '';
ALTER TABLE agent_memory ADD COLUMN story_order INTEGER DEFAULT 0;

-- character_trackers (角色追踪)
ALTER TABLE character_trackers ADD COLUMN unit_id TEXT DEFAULT '';

-- narrative_pressures (叙事压力)
ALTER TABLE narrative_pressures ADD COLUMN unit_id TEXT DEFAULT '';

-- world_state_snapshots (世界状态快照)
ALTER TABLE world_state_snapshots ADD COLUMN unit_id TEXT DEFAULT '';

-- scene_subtext_cards (潜文本卡)
ALTER TABLE scene_subtext_cards ADD COLUMN unit_id TEXT DEFAULT '';

-- consistency_logs (一致性日志)
ALTER TABLE consistency_logs ADD COLUMN unit_id TEXT DEFAULT '';

-- usage_records (使用记录)
ALTER TABLE usage_records ADD COLUMN unit_id TEXT DEFAULT '';

-- chapter_drafts (章节草稿)
ALTER TABLE chapter_drafts ADD COLUMN unit_id TEXT DEFAULT '';

-- chapter_change_log (章节变更日志)
ALTER TABLE chapter_change_log ADD COLUMN unit_id TEXT DEFAULT '';

-- entity_appearances (实体出现记录)
ALTER TABLE entity_appearances ADD COLUMN unit_id TEXT DEFAULT '';

-- chapter_briefs (章节大纲)
ALTER TABLE chapter_briefs ADD COLUMN unit_id TEXT DEFAULT '';
